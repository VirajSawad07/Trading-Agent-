"""Step B of docs/RESEARCH_PLAN.md (Revision 1): the index dip strategy on the demo account.

Runs the frozen Track 3 rules (src/research/index_dips.py) on 7 indexes, next to the gold
bot, with its own magic number (777102), ledger and state. Demo only: every order goes
through DemoGateway, which refuses a non-demo account.

Once a day per index, when a new daily bar has closed:
  - flat: buy if the close is above the 200-day average and RSI(2) is below 10;
  - holding: sell if the close is above the 5-day average or 10 days have passed.
The stop (3x ATR(14) below the fill) sits at the broker, so it works between checks.

Sized as a $100,000 account risking 0.5% (about $500) per trade; results are in R.
Known gap from the backtest: the backtest fills at the signal bar's close, this bot at
the next price it can trade, usually the next session's open. The ledger records both.

    python -m src.live.dip_trader              # run (demo orders)
    python -m src.live.dip_trader --dry-run    # log decisions, send no orders
    python -m src.live.dip_trader check        # replay every logged decision through the backtest rules
"""

import argparse
import json
import logging
import math
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from src.execution.demo_gateway import DemoGateway, LiveAccountError
from src.live.ledger import Ledger, read
from src.live.paper_trader import LIVE_ACCOUNT_EXIT, State
from src.research.index_dips import EXIT_MA, MAX_DAYS, RSI_MAX, STOP_ATR, indicators
from src.risk.risk_engine import OrderProposal

try:
    import MetaTrader5 as mt5
except ImportError:  # tests import the pure helpers without MT5
    mt5 = None

SYMBOLS = ["US500", "US30", "USTEC", "DE40", "AUS200", "FRA40", "EUSTX50"]  # JPN225 left out (Revision 1)
MAGIC = 777102
SIZING_EQUITY = 100_000.0
RISK_PCT = 0.005
KILL_R = -12.0          # Revision 1: stop new trades below -12 R in total
HISTORY_BARS = 600      # closed daily bars fetched per check (200-day average + room for data holes)
LEDGER = Path("reports/live/ledger_DIPS_D1.jsonl")
STATE = Path("reports/live/state_DIPS_D1.json")

log = logging.getLogger("dips")


# ----------------------------------------------------------------------------- pure logic

def decide(x: pd.DataFrame, held_bars: Optional[int]) -> tuple:
    """Rule decision on the last closed bar of `x` (output of index_dips.indicators).
    held_bars: closed bars since the entry signal bar, or None when flat.
    Returns (action, reason) with action in {"open", "close", None}."""
    last = x.iloc[-1]
    c, sma_t, sma_e, r, atr = last["close"], last["sma_trend"], last["sma_exit"], last["rsi"], last["atr"]
    if held_bars is None:
        if not (c > sma_t):
            return None, f"No trade: close {c:.1f} is not above the 200-day average {sma_t:.1f}."
        if not (r < RSI_MAX):
            return None, f"No trade: uptrend, but RSI(2) is {r:.1f}, not below {RSI_MAX:.0f}."
        if not (atr > 0):
            return None, "No trade: ATR not available."
        return "open", f"Dip in an uptrend: close {c:.1f} above the 200-day average {sma_t:.1f}, RSI(2) {r:.1f}."
    if c > sma_e:
        return "close", f"Exit: close {c:.1f} is back above the {EXIT_MA}-day average {sma_e:.1f}."
    if held_bars >= MAX_DAYS:
        return "close", f"Exit: held {held_bars} days, the {MAX_DAYS}-day limit."
    return None, f"Hold: day {held_bars}, close {c:.1f} still below the {EXIT_MA}-day average {sma_e:.1f}."


def lots_for(risk_usd: float, stop_dist: float, usd_per_unit_lot: float, min_lot: float, step: float,
             max_lot: float) -> float:
    """Largest lot (in steps) whose stop risks at most risk_usd; 0 if even the minimum is too big."""
    if stop_dist <= 0 or usd_per_unit_lot <= 0:
        return 0.0
    raw = risk_usd / (stop_dist * usd_per_unit_lot)
    lots = math.floor(raw / step + 1e-9) * step
    lots = min(round(lots, 8), max_lot)
    return lots if lots >= min_lot else 0.0


@dataclass
class DipState:
    start_utc: str = ""
    closed_pnl: float = 0.0
    total_r: float = 0.0
    halted: str = ""
    last_bar: dict = field(default_factory=dict)    # symbol -> last decided bar date
    last_exit: dict = field(default_factory=dict)   # symbol -> day of the last exit
    positions: dict = field(default_factory=dict)   # symbol -> open position details

    load = classmethod(State.load.__func__)
    save = State.save


# ----------------------------------------------------------------------------- trader

class DipTrader:
    def __init__(self, dry_run=False, symbols=SYMBOLS):
        self.dry_run, self.symbols = dry_run, symbols
        self.gateway = DemoGateway(magic_number=MAGIC)
        suffix = "_dry" if dry_run else ""
        self.ledger = Ledger(LEDGER.with_name(LEDGER.stem + suffix + LEDGER.suffix))
        self.state_path = STATE.with_name(STATE.stem + suffix + STATE.suffix)
        self.state = DipState.load(self.state_path)
        if not self.state.start_utc:
            self.state.start_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def connect(self) -> bool:
        ok = mt5.initialize(timeout=10000) and mt5.terminal_info() is not None and mt5.terminal_info().connected
        if ok:
            for s in self.symbols:
                mt5.symbol_select(s, True)
        return bool(ok)

    def closed_bars(self, sym: str) -> pd.DataFrame:
        rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_D1, 1, HISTORY_BARS)  # position 0 is still forming
        if rates is None or len(rates) < 210:
            raise RuntimeError(f"{sym}: not enough daily bars ({mt5.last_error()})")
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        return df.set_index("time")[["open", "high", "low", "close"]]

    # ---------------------------------------------------------------- closed trades

    def reconcile(self):
        open_by_ticket = {p.ticket: p for p in self.gateway.bot_positions()}
        for sym, info in list(self.state.positions.items()):
            if info.get("ticket") in open_by_ticket or info.get("pending"):
                continue
            deals = self.gateway.position_deals(int(info["ticket"]))
            exits = [d for d in deals if d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY)]
            if not exits:
                info["missing"] = info.get("missing", 0) + 1
                if info["missing"] > 20:
                    self.ledger.append("error", f"{sym} position #{info['ticket']} vanished with no closing deal.",
                                       symbol=sym, ticket=info["ticket"])
                    del self.state.positions[sym]
                continue
            pnl = sum(d.profit + d.commission + d.swap + getattr(d, "fee", 0.0) for d in deals)
            r = pnl / info["risk_usd"]
            reason = "stop loss" if exits[-1].reason == mt5.DEAL_REASON_SL else info.get("close_reason", "closed")
            self.state.closed_pnl += pnl
            self.state.total_r += r
            self.ledger.append("trade_closed", f"{sym} closed by {reason}: {pnl:+.2f} USD = {r:+.2f} R.",
                               symbol=sym, ticket=info["ticket"], signal_bar=info["signal_bar"],
                               exit_signal_bar=info.get("exit_signal_bar"), entry_price=info["entry_price"],
                               exit_price=exits[-1].price, exit_reason=reason, pnl_usd=round(pnl, 2),
                               r_net=round(r, 4), lots=info["lots"])
            # Server-time day of the exit: the backtest never re-enters on the bar it exited.
            self.state.last_exit[sym] = str(pd.to_datetime(exits[-1].time, unit="s").date())
            del self.state.positions[sym]
        if self.state.total_r <= KILL_R and not self.state.halted:
            self.state.halted = f"total {self.state.total_r:.2f} R is below {KILL_R} R"
            self.ledger.append("halted", f"No new trades: {self.state.halted} (Revision 1 stop rule).")

    # ---------------------------------------------------------------- orders

    def open(self, sym: str, x: pd.DataFrame, reason: str):
        bar = str(x.index[-1].date())
        atr, close = float(x["atr"].iloc[-1]), float(x["close"].iloc[-1])
        stop_dist = STOP_ATR * atr
        info = mt5.symbol_info(sym)
        tick = mt5.symbol_info_tick(sym)
        usd = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, sym, 1.0, tick.ask, tick.ask + 1.0)
        lots = lots_for(SIZING_EQUITY * RISK_PCT, stop_dist, usd or 0.0, info.volume_min, info.volume_step,
                        info.volume_max)
        details = dict(symbol=sym, signal_bar=bar, signal_close=close, atr=round(atr, 3), stop_dist=round(stop_dist, 3),
                       usd_per_unit_lot=usd, lots=lots)
        if lots == 0:
            self.ledger.append("skipped", f"{sym}: {reason} Skipped: the minimum lot risks more than "
                                          f"{SIZING_EQUITY * RISK_PCT:.0f} USD with this stop.", **details)
            return
        if self.dry_run:
            self.ledger.append("would_open", f"{sym}: {reason} Dry run: would buy {lots} lots.", **details)
            return
        sl = round(tick.ask - stop_dist, info.digits)
        res = self.gateway.send_order(OrderProposal(sym, "BUY", tick.ask, sl, 0.0, lots, "index_dips"), lots,
                                      client_tag=f"dip{sym[:5]}{x.index[-1]:%y%m%d}")
        if not res.success:
            # Market closed (e.g. European index at night): keep the signal and retry next check.
            self.state.positions[sym] = {"pending": True, "signal_bar": bar, "reason": reason}
            log.info("%s: order not filled yet (%s); will retry", sym, res.message)
            return
        pos = next((p for p in self.gateway.bot_positions(sym) if p.ticket == res.ticket), None)
        fill = pos.price_open if pos else res.price
        sl = round(fill - stop_dist, info.digits)
        if pos:
            self.gateway.modify_sltp(pos.ticket, sym, sl, 0.0)  # stop measured from the real fill, as in the backtest
        risk_usd = stop_dist * usd * lots
        self.state.positions[sym] = dict(ticket=pos.ticket if pos else res.ticket, signal_bar=bar, entry_price=fill,
                                         sl=sl, lots=lots, risk_usd=risk_usd)
        self.ledger.append("trade_opened", f"{sym}: {reason} Bought {lots} lots at {fill} (signal close {close}), "
                                           f"stop {sl}, risking {risk_usd:.2f} USD.",
                           **details, ticket=self.state.positions[sym]["ticket"], fill=fill, sl=sl,
                           risk_usd=round(risk_usd, 2), fill_vs_signal_close=round(fill - close, 3))

    def close(self, sym: str, bar: str, reason: str):
        info = self.state.positions[sym]
        pos = next((p for p in self.gateway.bot_positions(sym) if p.ticket == info["ticket"]), None)
        if pos is None:
            return  # already gone (stop); reconcile records it
        if self.dry_run:
            self.ledger.append("would_close", f"{sym}: {reason} Dry run.", symbol=sym, exit_signal_bar=bar)
            return
        info["exit_signal_bar"], info["close_reason"] = bar, reason
        if not self.gateway.close_position(pos, comment=f"dipexit{bar[2:].replace('-', '')}"):
            info["close_pending"] = True
            log.info("%s: close not filled yet; will retry", sym)
            return
        info.pop("close_pending", None)

    # ---------------------------------------------------------------- one check

    def step(self):
        self.reconcile()
        for sym in self.symbols:
            try:
                self.check_symbol(sym)
            except Exception as e:
                log.exception("%s failed", sym)
                self.ledger.append("error", f"{sym}: {type(e).__name__}: {e}", symbol=sym)
        self.state.save(self.state_path)

    def check_symbol(self, sym: str):
        pos = self.state.positions.get(sym)
        if pos and pos.get("close_pending"):
            self.close(sym, pos["exit_signal_bar"], pos["close_reason"])
            return
        bars = self.closed_bars(sym)
        bar = str(bars.index[-1].date())
        if pos and pos.get("pending"):
            if bar == pos["signal_bar"]:  # same signal, market was closed: try again
                del self.state.positions[sym]
                x = indicators(bars)
                return self.open(sym, x, pos["reason"])
            self.ledger.append("skipped", f"{sym}: entry signal of {pos['signal_bar']} never filled before the next "
                                          "bar closed; dropped.", symbol=sym, signal_bar=pos["signal_bar"])
            del self.state.positions[sym]
        if self.state.last_bar.get(sym) == bar:
            return
        x = indicators(bars)
        pos = self.state.positions.get(sym)
        held = None if pos is None else int((x.index > pd.Timestamp(pos["signal_bar"])).sum())
        action, reason = decide(x, held)
        blocked = action == "open" and self.state.last_exit.get(sym) == bar
        if blocked:
            action, reason = None, f"No trade: a position closed during this bar ({reason[:-1]}, but no same-bar re-entry)."
        last = x.iloc[-1]
        self.ledger.append("decision", f"{sym} {bar}: {reason}", symbol=sym, bar=bar, close=float(last["close"]),
                           sma200=float(last["sma_trend"]), sma5=float(last["sma_exit"]), rsi2=float(last["rsi"]),
                           atr=float(last["atr"]), held_bars=held, action=action,
                           reentry_blocked=blocked)
        self.state.last_bar[sym] = bar
        if action == "open":
            if self.state.halted:
                self.ledger.append("skipped", f"{sym}: entry skipped, trading halted ({self.state.halted}).", symbol=sym)
            else:
                self.open(sym, x, reason)
        elif action == "close":
            self.close(sym, bar, reason)

    def run(self, poll: int = 60, once: bool = False):
        if not self.connect():
            raise SystemExit("Could not connect to MT5. Open MT5 and log in to the demo account.")
        acc = self.gateway.verify_demo_account()
        self.ledger.append("session_start", f"Dip trader started on demo #{acc['login']} "
                                            f"({'dry run, no orders' if self.dry_run else 'placing demo orders'}).",
                           login=acc["login"], symbols=self.symbols, sizing_equity=SIZING_EQUITY, risk_pct=RISK_PCT,
                           magic=MAGIC)
        down = False
        try:
            while True:
                try:
                    info = mt5.terminal_info()
                    if info is None or not info.connected or mt5.account_info() is None:
                        if not down:
                            self.ledger.append("error", "Lost connection to MT5; reconnecting.")
                        down = True
                        self.connect()  # the gold bot's watchdog restarts a frozen terminal
                    else:
                        if down:
                            self.ledger.append("reconnected", "MT5 back.")
                        down = False
                        self.gateway.verify_demo_account()
                        self.step()
                except LiveAccountError:
                    raise
                except Exception as e:
                    log.exception("step failed")
                    self.ledger.append("error", f"Step failed: {type(e).__name__}: {e}")
                if once:
                    break
                time.sleep(poll)
        except KeyboardInterrupt:
            log.info("Stopped by user.")
        finally:
            self.state.save(self.state_path)
            self.ledger.append("session_stop", "Dip trader stopped.")


# ----------------------------------------------------------------------------- replay check

def replay_check(ledger_path=LEDGER) -> list:
    """Revision 1: every logged decision must match the backtest rules on the same bars."""
    from src.research.index_dips import load_bars
    problems = []
    decisions = [r for r in read(ledger_path) if r["event"] == "decision"]
    cache = {}
    for d in decisions:
        sym = d["symbol"]
        if sym not in cache:
            cache[sym] = indicators(load_bars(sym))
        x = cache[sym]
        x = x[x.index <= pd.Timestamp(d["bar"])]
        if x.empty or str(x.index[-1].date()) != d["bar"]:
            problems.append(f"{sym} {d['bar']}: bar not in downloaded data (re-download D1 first)")
            continue
        action, _ = decide(x, d["held_bars"])
        if d.get("reentry_blocked") and action == "open":
            action = None  # the backtest also skips entry on the bar of a stop exit
        if action != d["action"]:
            problems.append(f"{sym} {d['bar']}: bot did {d['action']}, backtest rules say {action}")
    return problems


def main():
    p = argparse.ArgumentParser(description="Index dip strategy on the demo account (Revision 1, Step B)")
    p.add_argument("command", nargs="?", default="run", choices=["run", "check"])
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--once", action="store_true")
    p.add_argument("--poll", type=int, default=60)
    args = p.parse_args()
    if args.command == "check":
        problems = replay_check()
        print("\n".join(problems) if problems else "OK: every decision matches the backtest rules.")
        sys.exit(1 if problems else 0)
    Path("reports/live/logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler("reports/live/logs/dips_D1.log")])
    try:
        DipTrader(args.dry_run).run(args.poll, args.once)
    except LiveAccountError as e:
        log.error("%s", e)
        sys.exit(LIVE_ACCOUNT_EXIT)


if __name__ == "__main__":
    main()

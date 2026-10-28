"""Paper-trade the harness-tested strategy on the MT5 DEMO account, with a forward ledger.

Runs exactly the model the harness evaluated (meta-labelled Donchian breakout with regime
features, expanding-window training) and mirrors the simulator's trade rules:

- Decide once per closed bar; enter at market right after the next bar opens.
- Stop = 2x ATR, target = 3x ATR, attached at the broker and re-anchored to the fill price.
- One position at a time. An opposite signal closes it and reverses. Close after 240 bars.
- Same-direction signals while in a position are ignored.

The model is refit every 3 months on all history to date, the same as an anchored fold.
Every bar's decision, every order and every closed trade goes into a hash-chained ledger
(src/live/ledger.py) with a plain-English reason, so the forward record can't be edited.

    python -m src.live.paper_trader --dry-run --once      # one decision, no orders
    python -m src.live.paper_trader                       # run continuously on demo

Demo only: the gateway refuses non-demo accounts on every order.
"""

import argparse
import json
import logging
import pickle
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from src.execution.demo_gateway import DemoGateway, LiveAccountError
from src.harness.costs import load_cost_model
from src.harness.meta_strategy import MetaLabelBreakout
from src.harness.walkforward import fit_for_live
from src.live.ledger import Ledger
from src.risk.risk_engine import AccountState, OrderProposal, RiskEngine
from src.run_harness import load_bars

try:
    import MetaTrader5 as mt5
except ImportError:  # tests import the pure helpers without MT5
    mt5 = None

TIMEFRAMES = {"H1": 16385, "H4": 16388}
BAR = {"H1": pd.Timedelta(hours=1), "H4": pd.Timedelta(hours=4)}
MAX_HOLD_BARS = 240
REFIT_EVERY = pd.DateOffset(months=3)
SIGNAL_TAIL = 8000  # bars used to compute live features (EMA200 etc. fully warmed up)

log = logging.getLogger("paper")


# ----------------------------------------------------------------------------- pure logic

def plan_actions(pos_dir: int, bars_held: int, signal: int, max_hold: int = MAX_HOLD_BARS) -> list:
    """What to do at a bar close, matching src/harness/simulator.py.
    Returns a list like [("close", "REVERSE"), ("open", -1)]."""
    actions, flat = [], pos_dir == 0
    if not flat:
        if signal == -pos_dir:
            actions.append(("close", "REVERSE"))
            flat = True
        elif bars_held >= max_hold:
            actions.append(("close", "TIME"))
            flat = True
    if flat and signal != 0:
        actions.append(("open", signal))
    return actions


def explain(info: dict, actions: list, pos_dir: int) -> str:
    """One plain-English sentence for the ledger."""
    side = {1: "up", -1: "down"}
    if not info["model_ready"]:
        why = "The model has no usable fit yet, so no trades are taken."
    elif info["breakout"] == 0:
        why = (f"No breakout: close {info['close']:.2f} is inside the channel "
               f"{info['channel_low']:.2f}-{info['channel_high']:.2f}.")
    elif info["signal"] == 0:
        why = (f"Breakout {side[info['breakout']]}, but the model gives only {info['probability']:.0%} "
               f"chance of profit (needs {info['threshold']:.0%}), so it is skipped.")
    else:
        why = (f"Breakout {side[info['breakout']]} and the model gives {info['probability']:.0%} chance of "
               f"profit (needs {info['threshold']:.0%}).")
    if not actions:
        if pos_dir and info["signal"] == pos_dir:
            why += " Already holding that direction, so nothing changes."
        elif pos_dir:
            why += " Holding the open position."
        return why
    parts = []
    for kind, arg in actions:
        if kind == "close":
            parts.append("close the open trade (" + ("opposite signal" if arg == "REVERSE" else f"held {MAX_HOLD_BARS} bars") + ")")
        else:
            parts.append(f"open a {'BUY' if arg > 0 else 'SELL'}")
    return why + " Plan: " + ", then ".join(parts) + "."


def bars_held(closed_index: pd.DatetimeIndex, entry_time: pd.Timestamp, bar: pd.Timedelta) -> int:
    """Closed bars since the bar the entry filled in (inclusive), as the simulator counts them."""
    entry_bar = entry_time.floor(bar)
    return int((closed_index >= entry_bar).sum())


def merge_bars(history: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    out = pd.concat([history, new])
    return out[~out.index.duplicated(keep="last")].sort_index()


# ----------------------------------------------------------------------------- state

@dataclass
class State:
    start_utc: str = ""
    sizing_equity: Optional[float] = None
    closed_pnl: float = 0.0
    peak_equity: float = 0.0
    day: str = ""
    day_start_equity: float = 0.0
    last_bar: str = ""
    halted: str = ""                       # non-empty = stopped for good (total drawdown)
    positions: dict = field(default_factory=dict)  # ticket -> details of open bot positions

    @classmethod
    def load(cls, path: Path) -> "State":
        return cls(**json.loads(path.read_text())) if path.exists() else cls()

    def save(self, path: Path):
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2, default=str))
        # Atomic swap, so a crash never leaves half a file. On Windows it fails while another
        # process (the dashboard, antivirus) has the file open, so retry briefly.
        for _ in range(20):
            try:
                tmp.replace(path)
                return
            except PermissionError:
                time.sleep(0.1)
        log.warning("state file busy; will save again next poll")


# ----------------------------------------------------------------------------- trader

class PaperTrader:
    def __init__(self, symbol="XAUUSD", timeframe="H1", data_tag="_2009", sizing_equity=3000.0,
                 dry_run=False, magic=777101, fill_window_min=15, out_dir="reports/live", risk_pct=None):
        self.symbol, self.tf, self.data_tag = symbol, timeframe, data_tag
        self.bar = BAR[timeframe]
        self.dry_run, self.fill_window = dry_run, timedelta(minutes=fill_window_min)
        self.costs = load_cost_model(symbol)
        self.strategy = MetaLabelBreakout(self.costs, regime_features=True)
        self.gateway = DemoGateway(magic_number=magic)
        self.risk = RiskEngine()
        if risk_pct:  # override the config's per-trade risk (the 2% min-lot cap and breakers stay)
            self.risk.max_risk_per_trade_pct = risk_pct
        out = Path(out_dir)
        (out / "logs").mkdir(parents=True, exist_ok=True)
        stem = f"{symbol}_{timeframe}"
        dry = "_dry" if dry_run else ""  # dry runs keep their own ledger so the real record stays clean
        self.ledger = Ledger(out / f"ledger_{stem}{dry}.jsonl")
        self.state_path = out / f"state_{stem}{dry}.json"
        self.state = State.load(self.state_path)
        if not self.state.start_utc:
            self.state.start_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self.state.sizing_equity = sizing_equity
        self.model_path = Path("models/live") / f"{stem}_{self.strategy.name}.pkl"
        self.model = None
        self.history = None
        self._last_tick_msc, self._tick_changed_at = None, time.monotonic()

    # ---------------------------------------------------------------- connection

    def connect(self, attempts: int = 6) -> bool:
        for i in range(attempts):
            if mt5.initialize(timeout=10000) and mt5.terminal_info() is not None and mt5.terminal_info().connected:
                mt5.symbol_select(self.symbol, True)
                return True
            wait = min(60, 5 * 2 ** i)
            log.warning("MT5 not connected (%s); retrying in %ss", mt5.last_error(), wait)
            mt5.shutdown()
            time.sleep(wait)
        return False

    def connected(self) -> bool:
        info = mt5.terminal_info()
        return info is not None and info.connected and mt5.account_info() is not None

    # ---------------------------------------------------------------- data + model

    def fetch_closed(self, count=600) -> tuple:
        rates = mt5.copy_rates_from_pos(self.symbol, TIMEFRAMES[self.tf], 0, count)
        if rates is None or len(rates) < 3:
            raise RuntimeError(f"no bars from MT5: {mt5.last_error()}")
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df = df.set_index("time").rename(columns={"tick_volume": "volume"})[["open", "high", "low", "close", "volume"]]
        return df.iloc[:-1], df.iloc[-1:]  # closed bars, the still-forming bar

    def load_history(self):
        try:
            hist = load_bars(self.symbol, self.tf, tag=self.data_tag)
        except FileNotFoundError:
            raise SystemExit(f"History file missing. Run: python -m src.data.fetch_history --symbols {self.symbol} "
                             f"--timeframes {self.tf} --start 2009-01-01 --tag {self.data_tag}")
        start = hist.index[-1] - timedelta(days=3)
        rates = mt5.copy_rates_range(self.symbol, TIMEFRAMES[self.tf], start.to_pydatetime(), datetime.now() + timedelta(days=2))
        if rates is not None and len(rates):
            gap = pd.DataFrame(rates)
            gap["time"] = pd.to_datetime(gap["time"], unit="s")
            gap = gap.set_index("time").rename(columns={"tick_volume": "volume"})[["open", "high", "low", "close", "volume"]]
            hist = merge_bars(hist, gap.iloc[:-1])
        self.history = hist
        log.info("History: %d bars %s -> %s", len(hist), hist.index[0], hist.index[-1])

    def ensure_model(self):
        last = self.history.index[-1]
        if self.model is None and self.model_path.exists():
            self.model = pickle.loads(self.model_path.read_bytes())
        if self.model and last < pd.Timestamp(self.model["trained_to"]) + REFIT_EVERY:
            return
        log.info("Fitting model on %d bars (all history to %s); this takes a minute...", len(self.history), last)
        t0 = time.time()
        params, model = fit_for_live(self.history, self.strategy, self.costs, anchored=True)
        self.model = {"params": params, "model": model, "trained_to": str(last),
                      "trained_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "bars": len(self.history)}
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        self.model_path.write_bytes(pickle.dumps(self.model))
        self.ledger.append("model_trained",
                           f"Refit on all {len(self.history):,} bars up to {last} (refit every 3 months); "
                           f"validation picked {params}." if params else
                           "Refit found no configuration that qualified, so no trades until the next refit.",
                           params=params, trained_to=str(last), seconds=round(time.time() - t0, 1))

    # ---------------------------------------------------------------- positions + equity

    def reconcile(self):
        """Record trades that closed (stop/target at the broker, or our own closes)."""
        open_tickets = {str(p.ticket) for p in self.gateway.bot_positions(self.symbol)}
        for ticket, info in list(self.state.positions.items()):
            if ticket in open_tickets:
                continue
            deals = self.gateway.position_deals(int(ticket))
            exits = [d for d in deals if d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY)]
            if not exits:
                info["missing"] = info.get("missing", 0) + 1
                if info["missing"] > 20:
                    self.ledger.append("error", f"Position #{ticket} vanished with no closing deal in history.", ticket=ticket)
                    del self.state.positions[ticket]
                continue
            pnl = sum(d.profit + d.commission + d.swap + getattr(d, "fee", 0.0) for d in deals)
            risk_usd = info["lots"] * self.costs.contract_size * info["sl_dist"]
            reason = {mt5.DEAL_REASON_SL: "stop loss", mt5.DEAL_REASON_TP: "take profit"}.get(exits[-1].reason, exits[-1].comment or "closed")
            self.state.closed_pnl += pnl
            self.ledger.append("trade_closed", f"Trade #{ticket} closed by {reason}: {pnl:+.2f} USD = {pnl / risk_usd:+.2f} R.",
                               ticket=ticket, signal_time=info["signal_time"], direction=info["direction"],
                               entry_price=info["entry_price"], exit_price=exits[-1].price,
                               exit_reason=reason, pnl_usd=round(pnl, 2), r_net=round(pnl / risk_usd, 4), lots=info["lots"])
            del self.state.positions[ticket]
        for p in self.gateway.bot_positions(self.symbol):  # adopt positions we lost track of (e.g. crash mid-order)
            if str(p.ticket) not in self.state.positions and p.sl:
                self.state.positions[str(p.ticket)] = dict(
                    direction=1 if p.type == mt5.POSITION_TYPE_BUY else -1, lots=p.volume, entry_price=p.price_open,
                    sl_dist=abs(p.price_open - p.sl), signal_time="unknown", entry_time=str(pd.to_datetime(p.time, unit="s")))
                self.ledger.append("position_adopted", f"Found open bot position #{p.ticket} not in state; tracking it.",
                                   ticket=p.ticket)

    def account(self) -> AccountState:
        """Risk-check equity: the planned account (sizing equity + this bot's P&L), or real equity."""
        real = self.gateway.get_account_state()
        if self.state.sizing_equity:
            floating = sum(p.profit + p.swap for p in self.gateway.bot_positions(self.symbol))
            real.equity = real.balance = self.state.sizing_equity + self.state.closed_pnl + floating
        st = self.state
        st.peak_equity = max(st.peak_equity or real.equity, real.equity)
        real.daily_starting_equity, real.peak_equity = st.day_start_equity or real.equity, st.peak_equity
        return real

    def new_day(self, server_day: str, equity: float):
        if self.state.day != server_day:
            self.state.day, self.state.day_start_equity = server_day, equity
            if not self.state.halted:
                self.risk.reset_kill_switch()  # the daily-loss breaker re-arms each day

    # ---------------------------------------------------------------- one step

    def step(self):
        closed, forming = self.fetch_closed()
        last_closed = closed.index[-1]
        tick = mt5.symbol_info_tick(self.symbol)
        if tick is not None and tick.time_msc != self._last_tick_msc:
            self._last_tick_msc, self._tick_changed_at = tick.time_msc, time.monotonic()
        self.reconcile()
        if str(last_closed) == self.state.last_bar:
            self.state.save(self.state_path)
            return

        self.history = merge_bars(self.history, closed)
        missed = 0
        if self.state.last_bar:
            missed = int((closed.index > pd.Timestamp(self.state.last_bar)).sum()) - 1
        self.state.last_bar = str(last_closed)
        self.ensure_model()

        acct = self.account()
        self.new_day(str(forming.index[0].date()), acct.equity)
        acct.daily_starting_equity = self.state.day_start_equity

        params, model = self.model["params"], self.model["model"]
        info = (self.strategy.explain_last(self.history.iloc[-SIGNAL_TAIL:], params, model) if params else
                {"bar_time": str(last_closed), "close": float(closed["close"].iloc[-1]), "breakout": 0, "signal": 0,
                 "probability": None, "threshold": None, "model_ready": False, "sl_dist": None, "tp_dist": None})

        positions = self.gateway.bot_positions(self.symbol)
        pos = positions[0] if positions else None
        pos_dir = 0 if pos is None else (1 if pos.type == mt5.POSITION_TYPE_BUY else -1)
        held = bars_held(self.history.index, pd.to_datetime(pos.time, unit="s"), self.bar) if pos else 0
        actions = plan_actions(pos_dir, held, info["signal"])

        server_now = pd.to_datetime(tick.time, unit="s") if tick else forming.index[0]
        late = server_now - forming.index[0] > self.fill_window
        stale = time.monotonic() - self._tick_changed_at > 120
        self.ledger.append("decision", explain(info, actions, pos_dir), symbol=self.symbol, timeframe=self.tf,
                           params=params, **info, position=pos_dir, bars_held=held, actions=actions,
                           missed_bars=missed, equity=round(acct.equity, 2), dry_run=self.dry_run)
        log.info("%s %s | %s", self.symbol, last_closed, explain(info, actions, pos_dir))

        for kind, arg in actions:
            if kind == "close":
                self.close(pos, arg)
            elif self.state.halted:
                self.ledger.append("risk_blocked", f"Not opening: trading halted ({self.state.halted}).")
            elif late or stale:
                self.ledger.append("risk_blocked", "Not opening: " + (
                    f"bar opened {server_now - forming.index[0]} ago, past the {self.fill_window} fill window, "
                    "so the fill would not match what was tested." if late else
                    "price feed has not updated for 2 minutes (market closed or feed stale)."))
            else:
                self.open(arg, info, acct, forming, str(last_closed))
        self.state.save(self.state_path)

    def close(self, pos, why):
        if self.dry_run:
            self.ledger.append("would_close", f"Dry run: would close #{pos.ticket} ({why}).", ticket=pos.ticket)
            return
        ok = self.gateway.close_position(pos, f"close_{why}")
        self.ledger.append("close_sent" if ok else "error",
                           f"Closed #{pos.ticket} at market ({why})." if ok else f"Failed to close #{pos.ticket} ({why}).",
                           ticket=pos.ticket)
        self.reconcile()

    def open(self, direction, info, acct, forming, signal_time):
        market = self.gateway.get_market_conditions(self.symbol)
        entry = market.ask if direction > 0 else market.bid
        sl = entry - direction * info["sl_dist"]
        tp = entry + direction * info["tp_dist"]
        proposal = OrderProposal(self.symbol, "BUY" if direction > 0 else "SELL", entry, sl, tp,
                                 strategy_id=self.strategy.name)
        ok, why, lots = self.risk.validate_proposal(proposal, acct, market, self.costs.contract_size)
        risk_usd = (lots or self.risk.min_lot_size) * self.costs.contract_size * info["sl_dist"]
        if not ok:
            if self.risk.kill_switch_active and "Total drawdown" in why:
                self.state.halted = why
            self.ledger.append("risk_blocked", f"Risk engine blocked the {proposal.action}: {why}",
                               spread_points=market.current_spread_points, equity=round(acct.equity, 2))
            return
        details = dict(action=proposal.action, lots=lots, entry=entry, sl=round(sl, 2), tp=round(tp, 2),
                       risk_usd=round(risk_usd, 2), risk_pct=round(risk_usd / acct.equity * 100, 2),
                       spread_points=market.current_spread_points, bar_open=float(forming["open"].iloc[0]))
        if self.dry_run:
            self.ledger.append("would_open", f"Dry run: would {proposal.action} {lots} lots, risking "
                                             f"{details['risk_usd']:.2f} USD ({details['risk_pct']}%).", **details)
            return
        tag = f"mbr{pd.Timestamp(signal_time):%y%m%d%H%M}"
        res = self.gateway.send_order(proposal, lots, client_tag=tag)
        if not res.success:
            self.ledger.append("error", f"Order failed: {res.message}", **details)
            return
        pos = next((p for p in self.gateway.bot_positions(self.symbol) if p.comment == tag), None)
        fill = pos.price_open if pos else res.price
        if pos:  # re-anchor stop/target to the real fill, as the simulator measures from the entry
            self.gateway.modify_sltp(pos.ticket, self.symbol, round(fill - direction * info["sl_dist"], 2),
                                     round(fill + direction * info["tp_dist"], 2))
        ticket = str(pos.ticket if pos else res.ticket)
        self.state.positions[ticket] = dict(direction=direction, lots=lots, entry_price=fill, sl_dist=info["sl_dist"],
                                            signal_time=signal_time, entry_time=str(pd.Timestamp.utcnow()))
        slip = direction * (fill - (details["bar_open"] + (self.costs.spread if direction > 0 else 0)))
        self.ledger.append("order_filled", f"{proposal.action} {lots} lots filled at {fill:.2f} "
                                           f"(cost vs tested next-open fill: {slip:+.2f}).",
                           ticket=ticket, fill=fill, fill_vs_model=round(slip, 3), **details)

    # ---------------------------------------------------------------- run loop

    def run(self, once=False, poll=10):
        if not self.connect():
            raise SystemExit("Could not connect to the MT5 terminal. Open MT5 and log in to the demo account.")
        acc = self.gateway.verify_demo_account()  # raises on a non-demo account
        self.ledger.append("session_start", f"Paper trader started on demo #{acc['login']} "
                                            f"({'dry run, no orders' if self.dry_run else 'placing demo orders'}).",
                           login=acc["login"], server=acc["server"], sizing_equity=self.state.sizing_equity, risk_pct=self.risk.max_risk_per_trade_pct,
                           magic=self.gateway.magic_number)
        self.load_history()
        self.ensure_model()
        try:
            while True:
                try:
                    if not self.connected():
                        self.ledger.append("error", "Lost connection to MT5; reconnecting.")
                        if not self.connect():
                            continue
                    self.gateway.verify_demo_account()
                    self.step()
                except LiveAccountError:  # only a non-demo account stops the bot; file errors etc. are logged
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
            self.ledger.append("session_stop", "Paper trader stopped.")
            mt5.shutdown()


def main():
    p = argparse.ArgumentParser(description="Paper-trade the tested model on MT5 demo")
    p.add_argument("--symbol", default="XAUUSD")
    p.add_argument("--timeframe", default="H1", choices=sorted(TIMEFRAMES))
    p.add_argument("--data-tag", default="_2009")
    p.add_argument("--sizing-equity", type=float, default=3000.0,
                   help="size trades as if the account held this much (gold needs ~$3,000 for 1%% risk at min lot)")
    p.add_argument("--dry-run", action="store_true", help="log decisions, send no orders")
    p.add_argument("--once", action="store_true", help="process the latest bar and exit")
    p.add_argument("--poll", type=int, default=10)
    p.add_argument("--magic", type=int, default=777101)
    p.add_argument("--risk-pct", type=float, default=None, help="risk per trade as a fraction, e.g. 0.005 = 0.5%% (default: config)")
    args = p.parse_args()

    Path("reports/live/logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(),
                                  logging.FileHandler(f"reports/live/logs/paper_{args.symbol}_{args.timeframe}.log")])
    PaperTrader(args.symbol, args.timeframe, args.data_tag, args.sizing_equity, args.dry_run, args.magic,
                risk_pct=args.risk_pct).run(args.once, args.poll)


if __name__ == "__main__":
    main()

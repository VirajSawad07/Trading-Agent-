"""Read-only overview of every bot for the dashboard: decisions, trades, positions and risk.

Pure functions over the ledgers and state files (so they can be tested without MT5), plus
`account_snapshot`, which only reads from MT5. Nothing here can place or change an order.
"""

import json
import time
from pathlib import Path

import yaml

from src.live.ledger import read, verify

LIVE = Path("reports/live")
BOTS = {
    "gold": {
        "name": "Gold breakout", "markets": "XAUUSD, hourly", "magic": 777101,
        "ledger": LIVE / "ledger_XAUUSD_H1.jsonl", "state": LIVE / "state_XAUUSD_H1.json",
        "log": LIVE / "logs" / "paper_XAUUSD_H1.log",
        "autostart_log": LIVE / "logs" / "autostart.log", "heartbeat_s": 120,
        "risk_config": "config/risk_limits_1k.yaml",
        "strategy": "Buys or sells a break of the 100-hour high/low when the model gives it at least 50%. "
                    "Stop 2x ATR, target 3x ATR, at most 240 hours.",
        "backtest_avg_r": 0.105,
    },
    "dips": {
        "name": "Index dips", "markets": "US500, US30, USTEC, DE40, AUS200, FRA40, EUSTX50, daily", "magic": 777102,
        "ledger": LIVE / "ledger_DIPS_D1.jsonl", "state": LIVE / "state_DIPS_D1.json",
        "log": LIVE / "logs" / "dips_D1.log",
        "autostart_log": LIVE / "logs" / "autostart_dips.log", "heartbeat_s": 300,
        "strategy": "Buys an index above its 200-day average after RSI(2) drops below 10. Sells above the "
                    "5-day average or after 10 days. Stop 3x ATR.",
        "backtest_avg_r": 0.062,
        "risk": {"sizing_equity": 100000.0, "risk_per_trade_pct": 0.5, "stop_new_trades_at_total_r": -12.0},
    },
}


# Every market a bot watches, with the bot that trades it (rule names; brokers may rename them).
MARKETS = {"XAUUSD": "gold", "US500": "dips", "US30": "dips", "USTEC": "dips", "DE40": "dips",
           "AUS200": "dips", "FRA40": "dips", "EUSTX50": "dips"}
MARKET_NAMES = {"XAUUSD": "Gold", "US500": "S&P 500", "US30": "Dow Jones", "USTEC": "Nasdaq 100", "DE40": "Germany 40",
                "AUS200": "Australia 200", "FRA40": "France 40", "EUSTX50": "Euro Stoxx 50"}


def files(key: str, signals: bool) -> dict:
    """Ledger, state and log paths: demo trading, or signals-only on a real account."""
    cfg = BOTS[key]
    if not signals:
        return {k: cfg[k] for k in ("ledger", "state", "log")}
    add = lambda p: p.with_name(p.stem + "_signals" + p.suffix)
    return {k: add(cfg[k]) for k in ("ledger", "state", "log")}


def _state(path: Path) -> tuple:
    try:
        return json.loads(path.read_text()), time.time() - path.stat().st_mtime
    except (OSError, ValueError):
        return {}, None


def _last_line(path: Path) -> str:
    try:
        lines = [x for x in path.read_text(encoding="utf-8", errors="replace").splitlines() if x.strip()]
        return lines[-1] if lines else ""
    except OSError:
        return ""


# ----------------------------------------------------------------------------- decisions

def classify(bot: str, r: dict) -> str:
    """One word for what a ledger decision meant: BUY, SELL, CLOSE, HOLD, SKIP or NO TRADE."""
    if bot == "dips":
        if r.get("action") == "open":
            return "BUY"
        if r.get("action") == "close":
            return "CLOSE"
        return "HOLD" if r.get("held_bars") is not None else "NO TRADE"
    acts = r.get("actions") or []
    kinds = [a[0] for a in acts]
    if "open" in kinds:
        side = next(a[1] for a in acts if a[0] == "open")
        return "BUY" if side > 0 else "SELL"
    if "close" in kinds:
        return "CLOSE"
    if r.get("position"):
        return "HOLD"
    if r.get("breakout"):
        return "SKIP"
    return "NO TRADE"


def _details(bot: str, r: dict) -> dict:
    keys = (["close", "channel_low", "channel_high", "probability", "threshold", "bars_held", "sl_dist"] if bot == "gold"
            else ["close", "sma200", "rsi2", "sma5", "atr", "held_bars"])
    return {k: r.get(k) for k in keys if r.get(k) is not None}


def decisions(bot: str, records: list) -> list:
    out = []
    for r in records:
        if r["event"] == "decision":
            out.append({"bot": bot, "time": r["ts_utc"], "market": r.get("symbol"),
                        "bar": r.get("bar") or r.get("bar_time"), "action": classify(bot, r),
                        "reason": r["reason"], "details": _details(bot, r)})
        elif r["event"] in ("risk_blocked", "skipped", "halted"):
            out.append({"bot": bot, "time": r["ts_utc"], "market": r.get("symbol"), "bar": r.get("signal_bar"),
                        "action": "BLOCKED", "reason": r["reason"], "details": {}})
    return out


def trades(bot: str, records: list) -> list:
    opened = {}
    rows = []
    for r in records:
        if r["event"] == "would_open":  # signals-only / dry run: a paper trade, no order
            rows.append({"bot": bot, "ticket": None, "paper": True, "market": r.get("symbol") or "XAUUSD",
                         "side": r.get("action", "BUY"), "opened": r["ts_utc"],
                         "entry": r.get("entry") or r.get("signal_close"), "stop": r.get("sl"), "target": r.get("tp"),
                         "lots": r.get("lots"), "risk_usd": r.get("risk_usd"), "closed": None, "exit": None,
                         "exit_reason": None, "pnl_usd": None, "r": None})
        elif r["event"] == "would_close":
            row = next((x for x in reversed(rows) if x.get("paper") and x["market"] == r.get("symbol")
                        and x["closed"] is None), None)
            if row:
                row.update(closed=r["ts_utc"], exit=r.get("exit_price"), exit_reason=r["reason"].split(": ", 1)[-1][:60],
                           r=r.get("r_gross"))
        elif r["event"] in ("trade_opened", "order_filled"):
            key = str(r.get("ticket"))
            opened[key] = r
            rows.append({"bot": bot, "ticket": key, "market": r.get("symbol") or "XAUUSD",
                         "side": r.get("action", "BUY"), "opened": r["ts_utc"], "entry": r.get("fill"),
                         "stop": r.get("sl"), "target": r.get("tp"), "lots": r.get("lots"),
                         "risk_usd": r.get("risk_usd"), "closed": None, "exit": None, "exit_reason": None,
                         "pnl_usd": None, "r": None})
        elif r["event"] == "trade_closed":
            key = str(r.get("ticket"))
            row = next((x for x in rows if x["ticket"] == key), None)
            if row is None:
                row = {"bot": bot, "ticket": key, "market": r.get("symbol") or "XAUUSD", "side": None,
                       "opened": None, "entry": r.get("entry_price"), "stop": None, "target": None,
                       "lots": r.get("lots"), "risk_usd": None}
                rows.append(row)
            row.update(closed=r["ts_utc"], exit=r.get("exit_price"), exit_reason=r.get("exit_reason"),
                       pnl_usd=r.get("pnl_usd"), r=r.get("r_net"))
    return rows


# ----------------------------------------------------------------------------- bots

def bot_status(key: str, now: float = None, signals: bool = False) -> dict:
    cfg = BOTS[key]
    f = files(key, signals)
    now = now or time.time()
    records = read(f["ledger"])
    ok, n, msg = verify(f["ledger"]) if f["ledger"].exists() else (True, 0, "no ledger yet")
    state, age = _state(f["state"])
    if age is not None:
        age = now - f["state"].stat().st_mtime
    stopped = bool(records) and records[-1]["event"] == "session_stop"
    running = age is not None and age < cfg["heartbeat_s"] and not stopped
    autostart = _last_line(cfg["autostart_log"])
    stop_reason = ""
    if not running:
        if "non-demo" in autostart and not signals:
            stop_reason = "Paused: MT5 is on a real account, where this bot only logs signals."
        elif stopped:
            stop_reason = "Stopped (last ledger entry is a session stop)."
        elif age is None:
            stop_reason = "Never started."
        else:
            stop_reason = f"No heartbeat for {round(age / 60)} min."
    closed = [r for r in records if r["event"] == "trade_closed"]
    rs = [r.get("r_net") or 0.0 for r in closed]
    risk = dict(cfg.get("risk", {}))
    if key == "gold":
        limits = yaml.safe_load(open(cfg["risk_config"]))["risk_limits"]
        sizing = state.get("sizing_equity")
        equity = (sizing or 0) + state.get("closed_pnl", 0.0)
        peak, day0 = state.get("peak_equity") or equity, state.get("day_start_equity") or equity
        risk.update(sizing_equity=sizing, risk_per_trade_pct=limits["max_risk_per_trade_pct"] * 100,
                    min_lot_allowed_up_to_pct=limits["max_min_lot_risk_pct"] * 100,
                    daily_loss_limit_pct=limits["max_daily_loss_pct"] * 100,
                    total_drawdown_limit_pct=limits["max_total_drawdown_pct"] * 100,
                    equity=equity, drawdown_pct=(1 - equity / peak) * 100 if peak else 0.0,
                    today_pct=(equity / day0 - 1) * 100 if day0 else 0.0)
    else:
        risk.update(total_r=state.get("total_r", 0.0), closed_pnl=state.get("closed_pnl", 0.0))
    starts = [r for r in records if r["event"] == "session_start"]
    return {
        "key": key, "name": cfg["name"], "signals_only": signals, "markets": cfg["markets"], "strategy": cfg["strategy"], "magic": cfg["magic"],
        "running": running, "stop_reason": stop_reason, "heartbeat_age_s": None if age is None else round(age),
        "halted": state.get("halted", ""), "ledger_ok": ok, "ledger_records": n, "ledger_msg": msg,
        "trades_closed": len(closed), "total_r": round(sum(rs), 3), "avg_r": round(sum(rs) / len(rs), 3) if rs else None,
        "win_rate": round(sum(r > 0 for r in rs) / len(rs), 3) if rs else None,
        "pnl_usd": round(sum(r.get("pnl_usd") or 0.0 for r in closed), 2), "backtest_avg_r": cfg["backtest_avg_r"],
        "decisions": sum(1 for r in records if r["event"] == "decision"),
        "errors": sum(1 for r in records if r["event"] == "error"),
        "since": starts[0]["ts_utc"] if starts else None, "risk": risk,
        "open_positions": state.get("positions", {}),
    }


def overview(now: float = None, signals: bool = False) -> dict:
    """signals=True: the real-account view (signals-only ledgers); False: the demo trading view."""
    bots = {k: bot_status(k, now, signals) for k in BOTS}
    all_dec, all_trades, events = [], [], []
    for k in BOTS:
        recs = read(files(k, signals)["ledger"])
        all_dec += decisions(k, recs)
        all_trades += trades(k, recs)
        events += [{"bot": k, "time": r["ts_utc"], "event": r["event"], "reason": r["reason"]}
                   for r in recs if r["event"] in ("session_start", "session_stop", "error", "reconnected",
                                                   "watchdog", "halted", "model_trained", "position_adopted")]
    by_time = lambda x: x["time"] or ""
    return {"bots": bots, "signals_only": signals,
            "markets": [{"market": m, "name": MARKET_NAMES[m], "bot": b} for m, b in MARKETS.items()],
            "decisions": sorted(all_dec, key=by_time, reverse=True)[:400],
            "trades": sorted(all_trades, key=lambda x: x["opened"] or x["closed"] or "", reverse=True),
            "events": sorted(events, key=by_time, reverse=True)[:150]}


def logs(signals: bool = False, lines: int = 60) -> dict:
    """The last lines of each bot's own log and its start script's log, newest last."""
    out = {}
    for k, cfg in BOTS.items():
        def tail(path):
            try:
                return path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
            except OSError:
                return []
        out[k] = {"bot_log": str(files(k, signals)["log"]), "lines": tail(files(k, signals)["log"]),
                  "autostart": tail(cfg["autostart_log"])[-15:]}
    return out


# ----------------------------------------------------------------------------- MT5 (read only)

def income(mt5, since=None) -> dict:
    """Closed-trade results of the whole account from MT5's deal history (bots and manual trades)."""
    from datetime import datetime
    deals = mt5.history_deals_get(since or datetime(2000, 1, 1), datetime.now()) or []
    by_pos, deposits = {}, 0.0
    for d in deals:
        if d.type == mt5.DEAL_TYPE_BALANCE:
            deposits += d.profit
            continue
        if d.type not in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL):
            continue
        by_pos.setdefault(d.position_id, []).append(d)
    results = []
    for ds in by_pos.values():
        if not any(d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY) for d in ds):
            continue  # still open
        results.append(sum(d.profit + d.swap + d.commission + getattr(d, "fee", 0.0) for d in ds))
    wins = [x for x in results if x > 0]
    losses = [x for x in results if x <= 0]
    return {"closed_trades": len(results), "wins": len(wins), "losses": len(losses),
            "win_rate": len(wins) / len(results) if results else None, "realised": round(sum(results), 2),
            "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else None, "deposits": round(deposits, 2)}


def quotes(mt5, server: str) -> dict:
    """Latest price and today's change for each market, under the broker's own symbol names."""
    from src.live.signals import broker_symbol
    out = {}
    for m in MARKETS:
        name = broker_symbol(m, server)
        mt5.symbol_select(name, True)
        t, d = mt5.symbol_info_tick(name), mt5.copy_rates_from_pos(name, mt5.TIMEFRAME_D1, 0, 2)
        if t is None:
            out[m] = {"broker": name, "bid": None}
            continue
        prev = float(d[-2]["close"]) if d is not None and len(d) == 2 else None
        out[m] = {"broker": name, "bid": t.bid, "ask": t.ask,
                  "change_pct": (t.bid / prev - 1) * 100 if prev else None,
                  "time": time.strftime("%Y-%m-%d %H:%M", time.gmtime(t.time))}
    return out


def account_snapshot(mt5) -> dict:
    acc = mt5.account_info()
    term = mt5.terminal_info()
    if acc is None:
        return {"connected": False}
    mode = {0: "DEMO", 1: "CONTEST", 2: "REAL"}.get(acc.trade_mode, str(acc.trade_mode))
    magic_bot = {cfg["magic"]: k for k, cfg in BOTS.items()}
    positions, open_risk = [], 0.0
    for p in mt5.positions_get() or []:
        buy = p.type == mt5.POSITION_TYPE_BUY
        risk = None
        if p.sl:
            loss = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL, p.symbol, p.volume,
                                         p.price_open, p.sl)
            risk = -loss if loss is not None else None
            open_risk += max(risk or 0.0, 0.0)
        positions.append({"ticket": p.ticket, "bot": magic_bot.get(p.magic, "manual / other"), "market": p.symbol,
                          "side": "BUY" if buy else "SELL", "lots": p.volume, "entry": p.price_open,
                          "price": p.price_current, "stop": p.sl or None, "target": p.tp or None,
                          "pnl": round(p.profit + p.swap, 2), "risk_to_stop": None if risk is None else round(risk, 2),
                          "risk_pct": None if risk is None or not acc.equity else round(risk / acc.equity * 100, 2),
                          "opened": time.strftime("%Y-%m-%d %H:%M", time.gmtime(p.time))})
    return {"connected": bool(term and term.connected), "mode": mode, "login": acc.login, "server": acc.server,
            "company": acc.company, "currency": acc.currency, "balance": acc.balance, "equity": acc.equity,
            "margin": acc.margin, "free_margin": acc.margin_free,
            "margin_level": acc.margin_level if acc.margin else None, "leverage": acc.leverage,
            "algo_trading": bool(term and term.trade_allowed), "positions": positions,
            "income": income(mt5), "quotes": quotes(mt5, acc.server),
            "open_risk": round(open_risk, 2), "open_risk_pct": round(open_risk / acc.equity * 100, 2) if acc.equity else None}

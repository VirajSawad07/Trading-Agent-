"""Read-only live dashboard for the bots.

    python -m src.live.dashboard            # then open http://127.0.0.1:8050

/      overview of every bot: account, decisions (buy, sell, hold, skip), trades and risk
/gold  the gold bot's own page, with its price chart

Shows what the paper trader is doing: running or not, its equity, the open position,
the price with the breakout channel, cumulative R against the backtest, and every
ledger decision with its plain-English reason. It reads the ledger/state files and
asks MT5 for quotes only. It cannot place, change or close trades.
"""

import argparse
import json
import time
from pathlib import Path

import pandas as pd
from fastapi import FastAPI
from fastapi.responses import FileResponse

from src.live.ledger import read, summary, verify
from src.live.overview import account_snapshot, overview

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

BACKTEST_AVG_R = 0.105  # meta_breakout_regime, anchored, XAUUSD H1 2011-2026 (HANDOVER.md)
HEARTBEAT_S = 60        # the trader saves its state every poll; older than this = not running
TIMEFRAMES = {"H1": 16385, "H4": 16388}

app = FastAPI(title="Paper trader dashboard")
CFG = {"symbol": "XAUUSD", "timeframe": "H1", "dir": Path("reports/live"), "magic": 777101}


def _paths():
    stem = f"{CFG['symbol']}_{CFG['timeframe']}"
    return CFG["dir"] / f"ledger_{stem}.jsonl", CFG["dir"] / f"state_{stem}.json"


def ledger_view(ledger_path: Path, state_path: Path, now: float = None) -> dict:
    """Everything the page needs from the ledger and state files (no MT5)."""
    now = now or time.time()
    records = read(ledger_path)
    ok, n, msg = verify(ledger_path)
    try:
        state = json.loads(state_path.read_text())
        age = now - state_path.stat().st_mtime
    except (OSError, ValueError):  # missing, or mid-save by the trader
        state, age = {}, None
    stopped = bool(records) and records[-1]["event"] == "session_stop"
    closed = [r for r in records if r["event"] == "trade_closed"]
    cum, curve = 0.0, []
    for i, r in enumerate(closed, 1):
        cum += r.get("r_net") or 0.0
        curve.append({"n": i, "time": r["ts_utc"], "r": r.get("r_net"), "cum_r": round(cum, 4),
                      "expected": round(i * BACKTEST_AVG_R, 4), "reason": r["reason"]})
    decisions = [r for r in records if r["event"] == "decision"]
    trained = [r for r in records if r["event"] == "model_trained"]
    sizing = state.get("sizing_equity")
    return {
        "running": age is not None and age < HEARTBEAT_S and not stopped,
        "heartbeat_age_s": None if age is None else round(age),
        "halted": state.get("halted", ""),
        "ledger_ok": ok, "ledger_records": n, "ledger_msg": msg,
        "summary": summary(ledger_path),
        "sizing_equity": sizing,
        "closed_pnl": round(state.get("closed_pnl", 0.0), 2),
        "peak_equity": state.get("peak_equity"),
        "day_start_equity": state.get("day_start_equity"),
        "last_decision": decisions[-1] if decisions else None,
        "params": (decisions[-1].get("params") if decisions else None) or (trained[-1].get("params") if trained else None),
        "backtest_avg_r": BACKTEST_AVG_R,
        "curve": curve,
        "recent": [{k: r.get(k) for k in ("seq", "ts_utc", "event", "reason", "bar_time", "probability")}
                   for r in records[-80:]][::-1],
        "session": next((r for r in reversed(records) if r["event"] == "session_start"), None),
    }


def _mt5_ready() -> bool:
    if mt5 is None:
        return False
    if mt5.terminal_info() is None and not mt5.initialize(timeout=5000):
        return False
    return mt5.account_info() is not None


@app.get("/")
def index():
    return FileResponse(Path(__file__).with_name("overview.html"))


@app.get("/gold")
def gold_page():
    return FileResponse(Path(__file__).with_name("dashboard.html"))


@app.get("/api/overview")
def api_overview():
    return overview()


@app.get("/api/account")
def api_account():
    return account_snapshot(mt5) if _mt5_ready() else {"connected": False}


@app.get("/api/ledger")
def api_ledger():
    return ledger_view(*_paths())


@app.get("/api/market")
def api_market(bars: int = 120):
    sym = CFG["symbol"]
    if not _mt5_ready():
        return {"connected": False}
    params = (ledger_view(*_paths()).get("params") or {})
    lookback = int(params.get("lookback", 100))
    rates = mt5.copy_rates_from_pos(sym, TIMEFRAMES[CFG["timeframe"]], 0, bars + lookback + 1)
    tick = mt5.symbol_info_tick(sym)
    info = mt5.symbol_info(sym)
    acc = mt5.account_info()
    out = {"connected": True, "symbol": sym, "demo": acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO,
           "login": acc.login, "lookback": lookback, "bars": [], "positions": []}
    if tick is not None:
        out.update(bid=tick.bid, ask=tick.ask, spread_points=round((tick.ask - tick.bid) / info.point, 1),
                   tick_time=str(pd.to_datetime(tick.time, unit="s")))
    if rates is not None and len(rates):
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        # Same channel the strategy uses: highest high / lowest low of the previous `lookback` bars.
        df["ch_high"] = df["high"].rolling(lookback).max().shift(1)
        df["ch_low"] = df["low"].rolling(lookback).min().shift(1)
        df = df.iloc[-bars:]
        out["bars"] = [{"t": str(r.time), "o": r.open, "h": r.high, "l": r.low, "c": r.close,
                        "ch": None if pd.isna(r.ch_high) else r.ch_high, "cl": None if pd.isna(r.ch_low) else r.ch_low}
                       for r in df.itertuples()]
    for p in mt5.positions_get(symbol=sym) or []:
        if p.magic == CFG["magic"]:
            out["positions"].append({"ticket": p.ticket, "side": "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
                                     "lots": p.volume, "entry": p.price_open, "sl": p.sl, "tp": p.tp,
                                     "profit": round(p.profit + p.swap, 2),
                                     "opened": str(pd.to_datetime(p.time, unit="s"))})
    return out


def main():
    import uvicorn
    p = argparse.ArgumentParser(description="Read-only paper trader dashboard")
    p.add_argument("--symbol", default="XAUUSD")
    p.add_argument("--timeframe", default="H1")
    p.add_argument("--port", type=int, default=8050)
    args = p.parse_args()
    CFG.update(symbol=args.symbol, timeframe=args.timeframe)
    print(f"Dashboard: http://127.0.0.1:{args.port}")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

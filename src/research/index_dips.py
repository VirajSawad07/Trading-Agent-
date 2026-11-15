"""Track 3 of docs/RESEARCH_PLAN.md: buying short dips in rising stock indexes (daily bars).

One trial, rules fixed in the plan before any result was seen (Connors-style RSI(2)):

  Index close above its 200-day average and RSI(2) below 10: buy at the close.
  Exit at the close once it is above the 5-day average, or after 10 days, or at a stop
  3x ATR(14) below entry (checked against each day's low; a gap below fills at the open).

R = the stop distance. Long only, one position per index. Entry pays the spread, every
fill pays slippage, and each night held pays 2%/yr financing (config/research_costs.yaml).

    python -m src.research.index_dips              # development period only
    python -m src.research.index_dips --holdout    # the locked hold-out, run once
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from src.harness.sanity import shuffled_bars
from src.harness.stats import deflated_sharpe, sharpe, trade_metrics

INDEXES = ["US500", "US30", "USTEC", "DE40", "JPN225", "AUS200", "FRA40", "EUSTX50"]
HOLDOUT_START = pd.Timestamp("2025-05-01")
TREND, RSI_N, RSI_MAX, EXIT_MA, MAX_DAYS, ATR_N, STOP_ATR = 200, 2, 10.0, 5, 10, 14, 3.0
GAP_DAYS = 7  # a data hole longer than this resets the indicators


def load_bars(sym: str, path_tmpl="data/raw/{}_D1_mt5.csv") -> pd.DataFrame:
    d = pd.read_csv(path_tmpl.format(sym), parse_dates=["time"]).set_index("time")
    return d[["open", "high", "low", "close"]][d.index.dayofweek < 5]


def rsi(close: pd.Series, n: int = RSI_N) -> pd.Series:
    """Wilder's RSI."""
    ch = close.diff()
    up = ch.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-ch.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def indicators(b: pd.DataFrame) -> pd.DataFrame:
    seg = (b.index.to_series().diff().dt.days > GAP_DAYS).cumsum()  # restart after a data hole
    out = []
    for _, g in b.groupby(seg):
        prev = g["close"].shift(1)
        tr = pd.concat([g["high"] - g["low"], (g["high"] - prev).abs(), (g["low"] - prev).abs()], axis=1).max(axis=1)
        out.append(g.assign(sma_trend=g["close"].rolling(TREND).mean(), sma_exit=g["close"].rolling(EXIT_MA).mean(),
                            rsi=rsi(g["close"]), atr=tr.rolling(ATR_N).mean()))
    return pd.concat(out)


def trades_for(sym: str, b: pd.DataFrame, cost: dict, cost_factor: float = 1.0) -> list:
    x = indicators(b)
    c, o, lo = x["close"].to_numpy(), x["open"].to_numpy(), x["low"].to_numpy()
    sma_t, sma_e, r, atr = (x[k].to_numpy() for k in ("sma_trend", "sma_exit", "rsi", "atr"))
    t = x.index
    spread = cost["spread_points"] * cost["point"] * cost_factor
    slip = cost["slippage_points"] * cost["point"] * cost_factor
    fin_rate = -cost["financing"]["long"] / 100 / 365 * cost_factor  # charge per calendar night
    trades, i = [], 0
    while i < len(x) - 1:
        if not (c[i] > sma_t[i] and r[i] < RSI_MAX and atr[i] > 0):
            i += 1
            continue
        entry, stop = c[i], c[i] - STOP_ATR * atr[i]
        risk = entry - stop
        exit_px, reason, j = None, "", i
        for j in range(i + 1, min(i + MAX_DAYS, len(x) - 1) + 1):
            if (t[j] - t[j - 1]).days > GAP_DAYS:   # data hole: close at the last known price
                exit_px, reason, j = c[j - 1], "DATA_GAP", j - 1
                break
            if lo[j] <= stop:
                exit_px, reason = min(o[j], stop), "STOP"
                break
            if c[j] > sma_e[j]:
                exit_px, reason = c[j], "MA_EXIT"
                break
            if j - i >= MAX_DAYS:
                exit_px, reason = c[j], "TIME"
                break
        if exit_px is None:  # ran out of data while open
            break
        nights = (t[j] - t[i]).days
        gross = exit_px - entry
        costs = spread + 2 * slip + fin_rate * entry * nights
        trades.append({"symbol": sym, "entry_time": t[i], "exit_time": t[j], "entry": entry, "exit": exit_px,
                       "stop": stop, "r_gross": gross / risk, "r_net": (gross - costs) / risk,
                       "bars_held": j - i, "exit_reason": reason})
        i = j + 1  # re-entry allowed from the day after the exit
    return trades


def run(bars: dict, costs: dict, cost_factor: float = 1.0) -> pd.DataFrame:
    rows = []
    for sym, b in bars.items():
        rows += trades_for(sym, b, costs[sym], cost_factor)
    return pd.DataFrame(rows)


def evaluate(holdout: bool = False, shuffles: int = 20) -> dict:
    costs = yaml.safe_load(open("config/research_costs.yaml"))
    full = {s: load_bars(s) for s in INDEXES}
    # Indicators need history, so the hold-out run sees earlier bars but only keeps
    # trades entered on or after its start.
    end = None if holdout else HOLDOUT_START
    bars = {s: (b if end is None else b[b.index < end]) for s, b in full.items()}
    keep = (lambda tr: tr[tr["entry_time"] >= HOLDOUT_START]) if holdout else (lambda tr: tr)
    tr = keep(run(bars, costs))
    days = pd.DatetimeIndex(sorted(set().union(*[set(b.index) for b in bars.values()])))
    days = days[days >= (HOLDOUT_START if holdout else tr["entry_time"].min())]
    span = (days[-1] - days[0]).days / 365.25
    daily = tr.groupby(tr["exit_time"].dt.normalize())["r_net"].sum().reindex(days, fill_value=0.0)
    res = {"period": "holdout" if holdout else "development", "from": str(days[0].date()), "to": str(days[-1].date()),
           "portfolio": trade_metrics(tr, span),
           "by_symbol": {s: trade_metrics(g, span) for s, g in tr.groupby("symbol")},
           "exit_reasons": tr["exit_reason"].value_counts().to_dict(),
           "daily_sharpe_annual": sharpe(daily.to_numpy()) * np.sqrt(252)}
    x2 = keep(run(bars, costs, cost_factor=2.0))
    res["cost_x2"] = {"total_r": float(x2["r_net"].sum()), "avg_r": float(x2["r_net"].mean())}
    if not holdout:
        null = [float(run({s: shuffled_bars(b, seed) for s, b in bars.items()}, costs)["r_net"].sum())
                for seed in range(shuffles)]
        res["shuffled"] = {"runs": shuffles, "mean_total_r": float(np.mean(null)),
                           "profitable_runs": int(sum(v > 0 for v in null)),
                           "total_r_p95": float(np.percentile(null, 95)), "all": [round(v, 1) for v in null]}
    # Deflated Sharpe over all 5 trials of the plan (Tracks 1-2 per-day Sharpes from their reports).
    t1 = json.load(open("reports/research/track1_development.json"))["trials"]
    t2 = json.load(open("reports/research/track2_development.json"))["trials"]
    per_day = ([v["daily_sharpe_annual"] for v in t1.values()] + [v["after_costs"]["sharpe_annual"] for v in t2.values()]
               + [res["daily_sharpe_annual"]])
    res["dsr_5_trials"] = deflated_sharpe(daily.to_numpy(), 5, np.array(per_day) / np.sqrt(252))["dsr"]
    p = res["portfolio"]
    if holdout:
        checks = {"positive_on_holdout": p["total_r"] > 0}
    else:
        checks = {"enough_trades (>=100)": p["trades"] >= 100,
                  "profitable_after_costs (avg R > 0, t > 2)": p["avg_r"] > 0 and p["t_stat"] > 2,
                  "survives_2x_costs": res["cost_x2"]["total_r"] > 0,
                  "deflated_sharpe >= 0.95": res["dsr_5_trials"] >= 0.95,
                  "beats 95% of shuffled runs": p["total_r"] > res["shuffled"]["total_r_p95"],
                  "harness_sane (shuffled mean loses)": res["shuffled"]["mean_total_r"] < 0}
    res["checks"] = {k: bool(v) for k, v in checks.items()}
    res["verdict"] = "PASS" if all(checks.values()) else "FAIL"
    tr.to_csv(f"reports/research/track3_{res['period']}_trades.csv", index=False)
    return res


def main():
    p = argparse.ArgumentParser(description="Track 3: buying dips in rising stock indexes")
    p.add_argument("--holdout", action="store_true", help="run on the locked hold-out (from 2025-05-01), once")
    p.add_argument("--shuffles", type=int, default=20)
    args = p.parse_args()
    Path("reports/research").mkdir(parents=True, exist_ok=True)
    out = evaluate(args.holdout, args.shuffles)
    path = Path(f"reports/research/track3_{out['period']}.json")
    path.write_text(json.dumps(out, indent=2, default=float))
    print(json.dumps(out, indent=2, default=float))
    print(f"Saved {path}")


if __name__ == "__main__":
    main()

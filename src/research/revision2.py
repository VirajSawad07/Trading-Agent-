"""Revision 2 of docs/RESEARCH_PLAN.md: two strategies that trade more often.

  Track 4  turn of the month: buy the 8 indexes at the close of the first bar on or after
           the month's second-to-last weekday, sell at the close of the next month's third
           bar (Lakonishok & Smidt 1988; McConnell & Xu 2008). Daily bars.
  Track 5  Track 3's dip rule (src/research/index_dips.py) unchanged, on 4-hour bars.

Both: long only, stop 3x ATR(14) below entry (R = stop distance), costs from
config/research_costs.yaml, development data up to 2025-04-30.

    python -m src.research.revision2 track4              # development period
    python -m src.research.revision2 track5
    python -m src.research.revision2 track4 --holdout    # once, only if development passes
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from src.harness.sanity import shuffled_bars
from src.harness.stats import deflated_sharpe, sharpe, trade_metrics
from src.research.index_dips import GAP_DAYS, STOP_ATR, indicators, load_bars, trades_for

INDEXES = ["US500", "US30", "USTEC", "DE40", "JPN225", "AUS200", "FRA40", "EUSTX50"]
HOLDOUT_START = pd.Timestamp("2025-05-01")
N_TRIALS = 7  # the plan's 5 plus Tracks 4 and 5
EXIT_BAR = 3  # sell at the close of the next month's third bar


# ----------------------------------------------------------------------------- Track 4

def entry_day(month: pd.Period) -> pd.Timestamp:
    """Second-to-last weekday of the month (holidays are not known in advance, so not used)."""
    return pd.date_range(month.start_time, month.end_time, freq="B")[-2]


def tom_trades(sym: str, b: pd.DataFrame, cost: dict, cost_factor: float = 1.0) -> list:
    x = indicators(b)
    t, c, o, lo, atr = x.index, x["close"].to_numpy(), x["open"].to_numpy(), x["low"].to_numpy(), x["atr"].to_numpy()
    month = t.to_period("M")
    spread = cost["spread_points"] * cost["point"] * cost_factor
    slip = cost["slippage_points"] * cost["point"] * cost_factor
    fin_rate = -cost["financing"]["long"] / 100 / 365 * cost_factor
    trades = []
    for m in month.unique():
        i = int(t.searchsorted(entry_day(m)))
        if i >= len(t) - 1 or month[i] != m or not atr[i] > 0:
            continue
        nxt = np.flatnonzero(month == m + 1)
        if len(nxt) < EXIT_BAR:
            continue  # data ends before the planned exit
        target = nxt[EXIT_BAR - 1]
        entry, stop = c[i], c[i] - STOP_ATR * atr[i]
        exit_px, reason, j = c[target], "TIME", target
        for k in range(i + 1, target + 1):
            if (t[k] - t[k - 1]).days > GAP_DAYS:   # data hole: close at the last known price
                exit_px, reason, j = c[k - 1], "DATA_GAP", k - 1
                break
            if lo[k] <= stop:
                exit_px, reason, j = min(o[k], stop), "STOP", k
                break
        risk = entry - stop
        costs = spread + 2 * slip + fin_rate * entry * (t[j] - t[i]).days
        trades.append({"symbol": sym, "entry_time": t[i], "exit_time": t[j], "entry": entry, "exit": exit_px,
                       "stop": stop, "r_gross": (exit_px - entry) / risk, "r_net": (exit_px - entry - costs) / risk,
                       "bars_held": j - i, "exit_reason": reason})
    return trades


# ----------------------------------------------------------------------------- shared evaluation

TRACKS = {
    "track4": {"fn": tom_trades, "path": "data/raw/{}_D1_mt5.csv", "name": "turn of the month (D1)"},
    "track5": {"fn": trades_for, "path": "data/raw/{}_H4_mt5.csv", "name": "dip rule on 4-hour bars"},
}


def run(track: str, bars: dict, costs: dict, cost_factor: float = 1.0) -> pd.DataFrame:
    fn = TRACKS[track]["fn"]
    rows = []
    for sym, b in bars.items():
        rows += fn(sym, b, costs[sym], cost_factor)
    return pd.DataFrame(rows)


def prior_trial_sharpes() -> list:
    """Annual Sharpe of every earlier trial in the plan, from their saved reports."""
    t1 = json.load(open("reports/research/track1_development.json"))["trials"]
    t2 = json.load(open("reports/research/track2_development.json"))["trials"]
    t3 = json.load(open("reports/research/track3_development.json"))
    return ([v["daily_sharpe_annual"] for v in t1.values()] + [v["after_costs"]["sharpe_annual"] for v in t2.values()]
            + [t3["daily_sharpe_annual"]])


def evaluate(track: str, holdout: bool = False, shuffles: int = 20, other_sharpe: float = None) -> dict:
    costs = yaml.safe_load(open("config/research_costs.yaml"))
    full = {s: load_bars(s, TRACKS[track]["path"]) for s in INDEXES if Path(TRACKS[track]["path"].format(s)).exists()}
    bars = full if holdout else {s: b[b.index < HOLDOUT_START] for s, b in full.items()}
    keep = (lambda tr: tr[tr["entry_time"] >= HOLDOUT_START].reset_index(drop=True)) if holdout else (lambda tr: tr)
    tr = keep(run(track, bars, costs))
    days = pd.DatetimeIndex(sorted(set().union(*[set(b.index.normalize()) for b in bars.values()])))
    days = days[days >= (HOLDOUT_START if holdout else tr["entry_time"].min().normalize())]
    span = (days[-1] - days[0]).days / 365.25
    daily = tr.groupby(tr["exit_time"].dt.normalize())["r_net"].sum().reindex(days, fill_value=0.0)
    res = {"track": track, "rule": TRACKS[track]["name"], "period": "holdout" if holdout else "development",
           "from": str(days[0].date()), "to": str(days[-1].date()), "markets": list(bars),
           "portfolio": trade_metrics(tr, span),
           "by_symbol": {s: trade_metrics(g, span) for s, g in tr.groupby("symbol")},
           "exit_reasons": tr["exit_reason"].value_counts().to_dict(),
           "daily_sharpe_annual": sharpe(daily.to_numpy()) * np.sqrt(252)}
    x2 = keep(run(track, bars, costs, cost_factor=2.0))
    res["cost_x2"] = {"total_r": float(x2["r_net"].sum()), "avg_r": float(x2["r_net"].mean())}
    p = res["portfolio"]
    if holdout:
        dev = pd.read_csv(f"reports/research/{track}_development_trades.csv")["r_net"].to_numpy()
        boot = np.random.default_rng(0).choice(dev, (10000, max(len(tr), 1)), replace=True).sum(axis=1)
        res["bootstrap_p5"] = float(np.percentile(boot, 5))
        checks = {"positive_on_holdout": p["total_r"] > 0, "above bootstrap 5th pct": p["total_r"] > res["bootstrap_p5"]}
    else:
        null = [float(run(track, {s: shuffled_bars(b, seed) for s, b in bars.items()}, costs)["r_net"].sum())
                for seed in range(shuffles)]
        se_total = float(tr["r_net"].std(ddof=1) * np.sqrt(len(tr)))
        res["shuffled"] = {"runs": shuffles, "mean_total_r": float(np.mean(null)), "total_r_p95": float(np.percentile(null, 95)),
                           "profitable_runs": int(sum(v > 0 for v in null)), "all": [round(v, 1) for v in null],
                           "se_of_total_r": se_total}
        per_year = prior_trial_sharpes() + [res["daily_sharpe_annual"]] + ([other_sharpe] if other_sharpe is not None else [])
        res["dsr_7_trials"] = deflated_sharpe(daily.to_numpy(), N_TRIALS, np.array(per_year) / np.sqrt(252))["dsr"]
        checks = {"enough_trades (>=100)": p["trades"] >= 100,
                  "profitable_after_costs (avg R > 0, t > 2)": p["avg_r"] > 0 and p["t_stat"] > 2,
                  "survives_2x_costs": res["cost_x2"]["total_r"] > 0,
                  "deflated_sharpe >= 0.95 (7 trials)": res["dsr_7_trials"] >= 0.95,
                  "beats 95% of shuffled runs": p["total_r"] > res["shuffled"]["total_r_p95"],
                  "beats shuffled mean by 2 SE": p["total_r"] > res["shuffled"]["mean_total_r"] + 2 * se_total}
    res["checks"] = {k: bool(v) for k, v in checks.items()}
    res["verdict"] = "PASS" if all(checks.values()) else "FAIL"
    tr.to_csv(f"reports/research/{track}_{res['period']}_trades.csv", index=False)
    return res


def main():
    p = argparse.ArgumentParser(description="Revision 2: turn of the month (track4) and 4-hour dips (track5)")
    p.add_argument("track", choices=sorted(TRACKS))
    p.add_argument("--holdout", action="store_true", help="run on the hold-out (from 2025-05-01), once")
    p.add_argument("--shuffles", type=int, default=20)
    args = p.parse_args()
    other = "track5" if args.track == "track4" else "track4"
    other_path = Path(f"reports/research/{other}_development.json")
    other_sharpe = json.loads(other_path.read_text())["daily_sharpe_annual"] if other_path.exists() else None
    out = evaluate(args.track, args.holdout, args.shuffles, other_sharpe)
    path = Path(f"reports/research/{args.track}_{out['period']}.json")
    path.write_text(json.dumps(out, indent=2, default=float))
    print(json.dumps(out, indent=2, default=float))
    print(f"Saved {path}")


if __name__ == "__main__":
    main()

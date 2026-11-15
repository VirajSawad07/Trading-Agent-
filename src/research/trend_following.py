"""Track 2 of docs/RESEARCH_PLAN.md: trend following across many markets (daily bars).

Two trials, rules fixed in the plan before any result was seen:

  A  tsmom_12m   Moskowitz, Ooi & Pedersen (2012). Long a market if its 12-month return is
                 positive, short if negative.
  B  tsmom_blend Hurst, Ooi & Pedersen (2017). Average of the signs of the 1-, 3- and
                 12-month returns, so the position is -1, -1/3, +1/3 or +1 of full size.

Both: each market's full position is 10%/sqrt(N) annual volatility, using its last 60
days of daily returns (N = markets trading that week), capped at 2x notional per market.
Positions are set at the last close of each week and held through the next week.
Every change in position pays half the spread plus slippage; open positions pay
financing every calendar night (config/research_costs.yaml).

Results are in percent of account equity, not R: positions are held continuously.

    python -m src.research.trend_following             # development period only
    python -m src.research.trend_following --holdout   # the locked hold-out, run once
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from src.harness.stats import deflated_sharpe, sharpe

UNIVERSE = ("EURUSD GBPUSD USDJPY AUDUSD USDCAD USDCHF NZDUSD EURJPY GBPJPY EURGBP "
            "XAUUSD XAGUSD XPTUSD XPDUSD COPPER US500 US30 USTEC DE40 JPN225 AUS200 FRA40 EUSTX50").split()
# UK100 is left out: its broker D1 history has a 3-year hole (2022-12 to 2026-03).
HOLDOUT_START = pd.Timestamp("2025-05-01")
VOL_DAYS, YEAR, MONTH = 60, 252, 21
WARMUP = YEAR + 1                 # a market trades once it has a full 12-month return
TARGET_VOL = 0.10                 # portfolio-level target, split as 10%/sqrt(N) per market
MAX_WEIGHT = 2.0
GAP_DAYS = 7                      # returns across a data hole longer than this are not counted
TRIALS = ["tsmom_12m", "tsmom_blend"]


# ----------------------------------------------------------------------------- data

def load_panel(symbols=UNIVERSE, path_tmpl="data/raw/{}_D1_mt5.csv") -> dict:
    closes, gaps = {}, {}
    for s in symbols:
        d = pd.read_csv(path_tmpl.format(s), parse_dates=["time"]).set_index("time")
        closes[s] = d["close"]
        gaps[s] = d.index.to_series().diff().dt.days > GAP_DAYS
    close = pd.DataFrame(closes).sort_index()
    close = close[close.index.dayofweek < 5]
    ret = close / close.ffill().shift(1) - 1           # return since the market's last close
    ret = ret.where(close.notna())
    for s in symbols:
        ret.loc[gaps[s][gaps[s]].index, s] = 0.0        # a hole is not a one-day move
    return {"close": close.ffill(), "ret": ret, "trading": close.notna()}


def load_costs(path="config/research_costs.yaml") -> dict:
    return yaml.safe_load(open(path))


# ----------------------------------------------------------------------------- signals

def signal(trial: str, close: pd.DataFrame) -> pd.DataFrame:
    if trial == "tsmom_12m":
        return np.sign(close / close.shift(YEAR) - 1)
    parts = [np.sign(close / close.shift(n) - 1) for n in (MONTH, 3 * MONTH, YEAR)]
    return sum(parts) / 3


def target_weights(trial: str, panel: dict) -> pd.DataFrame:
    """Weights decided at each week's last close (NaN on other days)."""
    close, ret = panel["close"], panel["ret"]
    vol = ret.rolling(VOL_DAYS, min_periods=VOL_DAYS).std() * np.sqrt(YEAR)
    history = panel["trading"].cumsum()
    live = (history > WARMUP) & panel["trading"] & vol.gt(0)
    sig = signal(trial, close).where(live)
    n = sig.notna().sum(axis=1).replace(0, np.nan)
    w = (sig * (TARGET_VOL / np.sqrt(n)).to_numpy()[:, None] / vol).clip(-MAX_WEIGHT, MAX_WEIGHT)
    week_end = pd.Series(close.index, index=close.index).groupby(close.index.to_period("W")).transform("max")
    w.loc[close.index != week_end.to_numpy()] = np.nan
    return w


# ----------------------------------------------------------------------------- simulation

def simulate(trial: str, panel: dict, costs: dict, cost_factor: float = 1.0, financing: bool = True) -> dict:
    close, ret = panel["close"], panel["ret"].fillna(0.0)
    held = target_weights(trial, panel).ffill().fillna(0.0)
    held = held.where(panel["trading"] | held.ne(0), 0.0)     # keep holding through a market's holiday
    prev = held.shift(1).fillna(0.0)                            # set at yesterday's close, earns today
    gross = (prev * ret).sum(axis=1)
    half_spread = pd.Series({s: (c["spread_points"] / 2 + c["slippage_points"]) * c["point"]
                             for s, c in costs.items()})[close.columns]
    trade_cost = ((held - prev).abs() * half_spread / close).sum(axis=1) * cost_factor
    nights = pd.Series(close.index, index=close.index).diff().dt.days.fillna(1).to_numpy()[:, None]
    fin = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    if financing:
        for s in close.columns:
            f = costs[s]["financing"]
            long_, short_ = f["long"], f["short"]
            if f["type"] == "points_per_night":
                rate = lambda side: side * costs[s]["point"] / close[s]
            else:  # annual_pct of notional
                rate = lambda side: pd.Series(side / 100 / 365, index=close.index)
            p = prev[s]
            charge = np.where(p > 0, p * rate(long_), -p * rate(short_))
            # Charges scale with the cost factor; credits never grow.
            charge = np.where(charge < 0, charge * cost_factor, charge)
            fin[s] = charge * nights[:, 0]
    net = gross - trade_cost + fin.sum(axis=1)
    flips = (np.sign(held) != np.sign(prev)) & held.ne(0)
    return {"net": net, "gross": gross, "trade_cost": trade_cost, "financing": fin.sum(axis=1),
            "weights": held, "entries": flips}


def shuffled_panel(panel: dict, seed: int) -> dict:
    """Null data: each market's daily returns in a random order (volatility kept, trends gone)."""
    rng = np.random.default_rng(seed)
    ret = panel["ret"].copy()
    for s in ret.columns:
        ok = ret[s].notna().to_numpy()
        vals = ret[s].to_numpy()[ok]
        ret.loc[ok, s] = vals[rng.permutation(len(vals))]
    first = panel["close"].bfill().iloc[0]
    close = (1 + ret.fillna(0.0)).cumprod() * first
    return {"close": close.where(panel["trading"]).ffill(), "ret": ret, "trading": panel["trading"]}


def summary(net: pd.Series, entries: pd.DataFrame = None) -> dict:
    net = net[net.index >= net.ne(0).idxmax()]  # from the first day with a position
    years = len(net) / YEAR
    eq = (1 + net).cumprod()
    out = {"from": str(net.index[0].date()), "to": str(net.index[-1].date()), "days": len(net),
           "annual_return_pct": float((eq.iloc[-1] ** (1 / years) - 1) * 100) if years > 0 else 0.0,
           "annual_vol_pct": float(net.std() * np.sqrt(YEAR) * 100),
           "sharpe_annual": sharpe(net.to_numpy()) * np.sqrt(YEAR),
           "t_stat": sharpe(net.to_numpy()) * np.sqrt(len(net)),
           "max_drawdown_pct": float((1 - eq / eq.cummax()).max() * 100),
           "total_return_pct": float((eq.iloc[-1] - 1) * 100)}
    if entries is not None:
        e = entries.loc[net.index]
        out["new_positions_per_year"] = float(e.sum().sum() / years)
    return out


# ----------------------------------------------------------------------------- evaluation

def evaluate(holdout: bool = False, shuffles: int = 20) -> dict:
    panel, costs = load_panel(), load_costs()
    period = (lambda s: s[s.index >= HOLDOUT_START]) if holdout else (lambda s: s[s.index < HOLDOUT_START])
    out = {"period": "holdout" if holdout else "development", "markets": list(panel["close"].columns), "trials": {}}
    nets = {}
    for trial in TRIALS:
        sim = simulate(trial, panel, costs)
        net = period(sim["net"])
        nets[trial] = net
        res = {"after_costs": summary(net, sim["entries"]),
               "before_costs": summary(period(sim["gross"])),
               "cost_pct_per_year": {"trading": float(period(sim["trade_cost"]).sum() / (len(net) / YEAR) * 100),
                                     "financing": float(period(sim["financing"]).sum() / (len(net) / YEAR) * 100)},
               "without_financing": summary(period(simulate(trial, panel, costs, financing=False)["net"])),
               "cost_x2": summary(period(simulate(trial, panel, costs, cost_factor=2.0)["net"]))}
        by = (period(sim["weights"].shift(1).fillna(0) * panel["ret"].fillna(0)))
        res["by_market_total_pct"] = {s: round(float(v) * 100, 2) for s, v in by.sum().sort_values().items()}
        if not holdout:
            null = [summary(period(simulate(trial, shuffled_panel(panel, seed), costs)["net"]))["sharpe_annual"]
                    for seed in range(shuffles)]
            res["shuffled_sharpe"] = {"runs": shuffles, "mean": float(np.mean(null)), "p95": float(np.percentile(null, 95)),
                                      "positive_runs": int(sum(x > 0 for x in null)), "all": [round(x, 2) for x in null]}
        out["trials"][trial] = res
    # Deflated Sharpe over every trial in the plan so far (Track 1's two + these two), counted as 5.
    t1 = json.load(open("reports/research/track1_development.json"))["trials"]
    per_day = [t1[k]["daily_sharpe_annual"] / np.sqrt(YEAR) for k in t1] + [sharpe(v.to_numpy()) for v in nets.values()]
    for trial in TRIALS:
        res, a = out["trials"][trial], out["trials"][trial]["after_costs"]
        res["dsr_5_trials"] = deflated_sharpe(nets[trial][nets[trial].ne(0).idxmax():].to_numpy(), 5, np.array(per_day))["dsr"]
        checks = {"profitable_after_costs (t > 2)": a["t_stat"] > 2,
                  "survives_2x_costs": res["cost_x2"]["total_return_pct"] > 0,
                  "deflated_sharpe >= 0.95": res["dsr_5_trials"] >= 0.95}
        if holdout:
            checks = {"positive_on_holdout": a["total_return_pct"] > 0}
        else:
            checks["beats 95% of shuffled runs"] = a["sharpe_annual"] > res["shuffled_sharpe"]["p95"]
            checks["harness_sane (shuffled mean <= 0)"] = res["shuffled_sharpe"]["mean"] <= 0
        res["checks"] = {k: bool(v) for k, v in checks.items()}
        res["verdict"] = "PASS" if all(checks.values()) else "FAIL"
    return out


def main():
    p = argparse.ArgumentParser(description="Track 2: trend following across markets")
    p.add_argument("--holdout", action="store_true", help="run on the locked hold-out (from 2025-05-01), once")
    p.add_argument("--shuffles", type=int, default=20)
    args = p.parse_args()
    Path("reports/research").mkdir(parents=True, exist_ok=True)
    out = evaluate(args.holdout, args.shuffles)
    path = Path(f"reports/research/track2_{out['period']}.json")
    path.write_text(json.dumps(out, indent=2, default=float))
    print(json.dumps(out, indent=2, default=float))
    print(f"Saved {path}")


if __name__ == "__main__":
    main()

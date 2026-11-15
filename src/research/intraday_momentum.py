"""Track 1 of docs/RESEARCH_PLAN.md: intraday momentum on US stock indexes (half-hour bars).

Two trials, rules fixed in the plan before any result was seen:

  A  noise_band  Zarattini, Aziz & Barbon (2024). At each half-hour close from 10:00 to
     15:30 New York time, go long above the upper noise band and short below the lower
     one. Band = max/min(today's open, yesterday's close) x (1 +/- sigma), where sigma is
     the average absolute move from the open at that time of day over the previous 14
     days. Exit when the close crosses back through the band or the day's VWAP (whichever
     is tighter), or at 16:00. One position at a time per index.
  B  gao_last_half_hour  Gao, Han, Li & Zhou (2018). The return from yesterday's 16:00
     close to 10:00 sets the direction of a trade held from 15:30 to 16:00.

R unit: A uses the band half-width at entry (sigma x open); B uses the average absolute
15:30-16:00 move over the previous 14 days. Fills are at half-hour closes: buys pay the
spread, and every fill pays slippage. Trades close before 16:00, so there is no swap.

Broker bars are in server time (EET/EEST, EU daylight-saving rules); they are converted
to New York time so the session is right in the weeks when the two clocks change apart.

    python -m src.research.intraday_momentum                    # development period only
    python -m src.research.intraday_momentum --holdout          # the locked hold-out, run once
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.harness.costs import CostModel, load_cost_model
from src.harness.stats import deflated_sharpe, sharpe, trade_metrics

SYMBOLS = ["US500", "US30", "USTEC"]
HOLDOUT_START = pd.Timestamp("2025-05-01")
LOOKBACK_DAYS = 14
SESSION = [f"{h:02d}:{m:02d}" for h in range(9, 16) for m in (0, 30)][1:]  # 09:30 ... 15:30 bar opens
N_BARS = len(SESSION)  # 13 half-hour bars, 09:30-16:00
TRIALS = ["noise_band", "gao_last_half_hour"]


# ----------------------------------------------------------------------------- data

def load_session(symbol: str, path_tmpl: str = "data/raw/{}_M30_mt5.csv") -> dict:
    """Full regular-session days as arrays of shape (days, 13). Days with missing bars
    (half days, data holes) are dropped."""
    df = pd.read_csv(path_tmpl.format(symbol), parse_dates=["time"])
    ny = df["time"].dt.tz_localize("Europe/Athens", ambiguous="NaT", nonexistent="NaT").dt.tz_convert("America/New_York")
    df = df.assign(hm=ny.dt.strftime("%H:%M"), day=ny.dt.tz_localize(None).dt.normalize()).dropna(subset=["hm"])
    df = df[df["hm"].isin(SESSION)]
    full = df.groupby("day")["hm"].transform("size") == N_BARS
    df = df[full].sort_values(["day", "hm"])
    days = df["day"].drop_duplicates().to_numpy()
    shape = (len(days), N_BARS)
    get = lambda c: df[c].to_numpy(float).reshape(shape)
    s = {"days": pd.DatetimeIndex(days), "open": get("open"), "high": get("high"), "low": get("low"),
         "close": get("close"), "volume": np.maximum(get("volume"), 1.0)}
    # Broken stretches: the broker's Oct-Dec 2024 half-hour bars are near-flat (median range
    # ~0.1-0.5 bps against ~15-30 normally), so highs, lows and closes there are not real.
    # Drop any day whose median bar range is under a fifth of the symbol's typical day.
    day_range = np.median((s["high"] - s["low"]) / s["close"], axis=1)
    ok = day_range >= 0.2 * np.median(day_range)
    return {k: v[ok] for k, v in s.items()}


def shuffle_within_days(s: dict, seed: int) -> dict:
    """Null data for the sanity test: inside each day, shuffle the order of the half-hour
    bars (each bar keeps its own shape and size, the day keeps its open and its range of
    moves). Any time-of-day momentum is destroyed; volatility is kept."""
    rng = np.random.default_rng(seed)
    o, h, l, c = (s[k] for k in ("open", "high", "low", "close"))
    prev_c = np.concatenate([o[:, :1], c[:, :-1]], axis=1)
    rel = np.stack([o / prev_c, h / o, l / o, c / o], axis=2)
    out = {k: np.empty_like(o) for k in ("open", "high", "low", "close")}
    for d in range(len(o)):
        r = rel[d, rng.permutation(N_BARS)]
        r[0, 0] = 1.0  # the day still opens at its real open
        last = o[d, 0]
        for j in range(N_BARS):
            op = last * r[j, 0]
            out["open"][d, j], out["high"][d, j] = op, op * r[j, 1]
            out["low"][d, j], out["close"][d, j] = op * r[j, 2], op * r[j, 3]
            last = out["close"][d, j]
    return {**s, **out}


def trailing_mean(x: np.ndarray, n: int = LOOKBACK_DAYS) -> np.ndarray:
    """Mean of the previous n rows (today excluded). NaN until n rows exist."""
    cs = np.cumsum(np.concatenate([np.zeros_like(x[:1]), x]), axis=0)
    out = np.full(x.shape, np.nan)
    out[n:] = (cs[n:-1] - cs[:-n - 1]) / n
    return out


# ----------------------------------------------------------------------------- trials

def _trade(day, sym, side, entry_bar, exit_bar, entry, exit_, r_unit, costs: CostModel, reason):
    gross = side * (exit_ - entry)
    cost = costs.spread + 2 * costs.slippage
    return {"symbol": sym, "day": day, "side": side, "entry_bar": SESSION[entry_bar],
            "exit_bar": SESSION[exit_bar] if exit_bar < N_BARS else "16:00", "entry": entry, "exit": exit_,
            "r_unit": r_unit, "r_gross": gross / r_unit, "r_net": (gross - cost) / r_unit,
            "bars_held": exit_bar - entry_bar, "exit_reason": reason}


def noise_band(s: dict, sym: str, costs: CostModel) -> list:
    o, c = s["open"], s["close"]
    day_open = o[:, :1]
    move = np.abs(c / day_open - 1)                 # |close / open - 1| at each half-hour close
    sigma = trailing_mean(move)                      # previous 14 days only
    prev_close = np.concatenate([[np.nan], c[:-1, -1]])
    top = np.fmax(day_open[:, 0], prev_close)        # gap adjustment: band starts from the wider of the two
    bot = np.fmin(day_open[:, 0], prev_close)
    tp = (s["high"] + s["low"] + c) / 3
    vwap = np.cumsum(tp * s["volume"], axis=1) / np.cumsum(s["volume"], axis=1)
    trades = []
    for d in range(len(c)):
        if np.isnan(sigma[d]).any() or np.isnan(prev_close[d]):
            continue
        pos, entry, entry_bar, r_unit = 0, 0.0, 0, 0.0
        for j in range(N_BARS):
            px = c[d, j]
            ub, lb = top[d] * (1 + sigma[d, j]), bot[d] * (1 - sigma[d, j])
            if pos and j == N_BARS - 1:
                trades.append(_trade(s["days"][d], sym, pos, entry_bar, N_BARS, entry, px, r_unit, costs, "CLOSE"))
                pos = 0
                break
            if pos == 1 and px < max(ub, vwap[d, j]) or pos == -1 and px > min(lb, vwap[d, j]):
                trades.append(_trade(s["days"][d], sym, pos, entry_bar, j + 1, entry, px, r_unit, costs, "STOP"))
                pos = 0
                continue  # no new entry on the bar that closed a trade
            if pos == 0 and j < N_BARS - 1:
                side = 1 if px > ub else -1 if px < lb else 0
                if side:
                    pos, entry, entry_bar = side, px, j + 1
                    r_unit = sigma[d, j] * day_open[d, 0]
    return trades


def gao_last_half_hour(s: dict, sym: str, costs: CostModel) -> list:
    c = s["close"]
    prev_close = np.concatenate([[np.nan], c[:-1, -1]])
    first = c[:, 0] / prev_close - 1                  # yesterday 16:00 -> today 10:00
    last_move = np.abs(c[:, -1] / c[:, -2] - 1)       # 15:30 -> 16:00
    r_pct = trailing_mean(last_move)
    trades = []
    for d in range(len(c)):
        if np.isnan(first[d]) or np.isnan(r_pct[d]) or first[d] == 0:
            continue
        side = 1 if first[d] > 0 else -1
        entry = c[d, -2]
        trades.append(_trade(s["days"][d], sym, side, N_BARS - 1, N_BARS, entry, c[d, -1],
                             r_pct[d] * entry, costs, "CLOSE"))
    return trades


TRIAL_FN = {"noise_band": noise_band, "gao_last_half_hour": gao_last_half_hour}


# ----------------------------------------------------------------------------- evaluation

def run_trial(trial: str, sessions: dict, cost_factor: float = 1.0) -> pd.DataFrame:
    rows = []
    for sym, s in sessions.items():
        rows += TRIAL_FN[trial](s, sym, load_cost_model(sym).scaled(cost_factor))
    return pd.DataFrame(rows)


def split(s: dict, holdout: bool) -> dict:
    keep = s["days"] >= HOLDOUT_START if holdout else s["days"] < HOLDOUT_START
    # The hold-out keeps the 14 prior days so its first sigma uses only earlier data.
    if holdout:
        first = int(np.argmax(keep))
        keep[max(0, first - LOOKBACK_DAYS - 1):first] = True
    return {k: (v[keep] if k != "days" else v[keep]) for k, v in s.items()}


def daily_portfolio_r(trades: pd.DataFrame, days: pd.DatetimeIndex) -> pd.Series:
    if trades.empty:
        return pd.Series(0.0, index=days)
    return trades.groupby("day")["r_net"].sum().reindex(days, fill_value=0.0)


def evaluate(holdout: bool = False, shuffles: int = 20) -> dict:
    sessions = {sym: split(load_session(sym), holdout) for sym in SYMBOLS}
    first_day = HOLDOUT_START if holdout else None
    all_days = pd.DatetimeIndex(sorted(set().union(*[set(s["days"]) for s in sessions.values()])))
    if first_day is not None:
        all_days = all_days[all_days >= first_day]
    span_years = (all_days[-1] - all_days[0]).days / 365.25
    out = {"period": "holdout" if holdout else "development",
           "from": str(all_days[0].date()), "to": str(all_days[-1].date()),
           "days": {sym: int(len(s["days"])) for sym, s in sessions.items()}, "trials": {}}
    daily = {}
    for trial in TRIALS:
        tr = run_trial(trial, sessions)
        if first_day is not None and not tr.empty:
            tr = tr[tr["day"] >= first_day]
        daily[trial] = daily_portfolio_r(tr, all_days)
        res = {"portfolio": trade_metrics(tr, span_years),
               "by_symbol": {sym: trade_metrics(g, span_years) for sym, g in tr.groupby("symbol")},
               "daily_sharpe_annual": sharpe(daily[trial].to_numpy()) * np.sqrt(252)}
        stress = run_trial(trial, sessions, cost_factor=2.0)
        if first_day is not None and not stress.empty:
            stress = stress[stress["day"] >= first_day]
        res["cost_x2"] = {"total_r": float(stress["r_net"].sum()), "avg_r": float(stress["r_net"].mean())}
        if not holdout:
            null = []
            for seed in range(shuffles):
                sh = {sym: shuffle_within_days(s, seed) for sym, s in sessions.items()}
                null.append(float(run_trial(trial, sh)["r_net"].sum()))
            res["shuffled"] = {"runs": shuffles, "mean_total_r": float(np.mean(null)),
                               "profitable_runs": int(sum(x > 0 for x in null)),
                               "total_r_p95": float(np.percentile(null, 95)), "all": [round(x, 1) for x in null]}
        tr.to_csv(f"reports/research/track1_{trial}_{out['period']}_trades.csv", index=False)
        out["trials"][trial] = res
    sharpes = np.array([sharpe(v.to_numpy()) for v in daily.values()])
    for trial in TRIALS:
        res = out["trials"][trial]
        # Counted against all 5 trials declared in the plan; only these 2 have run, so the
        # spread of trial Sharpes comes from them.
        res["dsr_5_trials"] = deflated_sharpe(daily[trial].to_numpy(), 5, sharpes)["dsr"]
        p = res["portfolio"]
        checks = {"enough_trades (>=300)": p["trades"] >= 300,
                  "profitable_after_costs (avg R > 0, t > 2)": p["avg_r"] > 0 and p["t_stat"] > 2,
                  "survives_2x_costs": res["cost_x2"]["total_r"] > 0,
                  "deflated_sharpe >= 0.95": res["dsr_5_trials"] >= 0.95}
        if not holdout:
            checks["beats 95% of shuffled runs"] = p["total_r"] > res["shuffled"]["total_r_p95"]
            checks["harness_sane (shuffled mean loses)"] = res["shuffled"]["mean_total_r"] < 0
        res["checks"] = checks
        res["verdict"] = "PASS" if all(checks.values()) else "FAIL"
    return out


def main():
    p = argparse.ArgumentParser(description="Track 1: intraday momentum on US indexes")
    p.add_argument("--holdout", action="store_true", help="run on the locked hold-out (from 2025-05-01), once")
    p.add_argument("--shuffles", type=int, default=20)
    args = p.parse_args()
    Path("reports/research").mkdir(parents=True, exist_ok=True)
    out = evaluate(args.holdout, args.shuffles)
    path = Path(f"reports/research/track1_{out['period']}.json")
    path.write_text(json.dumps(out, indent=2, default=float))
    print(json.dumps(out, indent=2, default=float))
    print(f"Saved {path}")


if __name__ == "__main__":
    main()

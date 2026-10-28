"""Run a strategy through the honest test harness.

    python -m src.run_harness --symbol XAUUSD --timeframe H1 --strategy ema_cross

Writes reports/harness/<symbol>_<tf>_<strategy>.json and the OOS trade list as CSV.
"""

import argparse
import json
import math
from pathlib import Path

import pandas as pd
from rich.console import Console
from rich.table import Table

from src.harness.account import simulate_account
from src.harness.costs import load_cost_model
from src.harness.meta_strategy import MetaLabelBreakout
from src.harness.sanity import random_walk_test
from src.harness.stats import deflated_sharpe, pbo_cscv, sharpe, trade_metrics
from src.harness.strategies import STRATEGIES
from src.harness.walkforward import check_no_lookahead, run_walk_forward


def load_bars(symbol: str, timeframe: str, data_dir: str = "data/raw", tag: str = "") -> pd.DataFrame:
    path = Path(data_dir) / f"{symbol}_{timeframe}_mt5{tag}.csv"
    df = pd.read_csv(path, parse_dates=["time"]).set_index("time").sort_index()
    return df[["open", "high", "low", "close", "volume"]]


def prior_trials(symbol: str, exclude_stem: str, report_dir: str = "reports/harness") -> int:
    """Configurations already tried on this symbol in earlier saved runs (any timeframe or data)."""
    total = 0
    for f in Path(report_dir).glob(f"{symbol}_*.json"):
        if f.stem != exclude_stem:
            total += json.loads(f.read_text()).get("configs_tried", 0)
    return total


def evaluate(bars, strategy, costs, n_random: int, account_sizes, risk_pct, wf_kwargs, earlier_trials: int = 0) -> dict:
    grid = strategy.param_grid()
    half = bars.iloc[: len(bars) // 2]
    lookahead_ok = all(
        check_no_lookahead(bars, strategy, p, model=strategy.fit(half, p) if strategy.trainable else None)
        for p in grid[:: max(1, len(grid) // 3)]
    )

    wf = run_walk_forward(bars, strategy, costs, **wf_kwargs)
    oos = wf.oos_trades
    span_years = (bars.index[-1] - wf.folds[0].test_start).days / 365.25 if wf.folds else 0.0
    m = trade_metrics(oos, span_years)

    days_per_year = len(wf.oos_daily_r) / span_years if span_years else 252
    trial_sr = [sharpe(wf.config_daily_r[c]) for c in wf.config_daily_r]
    dsr = deflated_sharpe(wf.oos_daily_r.to_numpy(), wf.n_configs, trial_sr)
    # Same, but counting every configuration ever tried on this symbol as a trial.
    dsr_all = deflated_sharpe(wf.oos_daily_r.to_numpy(), wf.n_configs + earlier_trials, trial_sr)
    pbo = pbo_cscv(wf.config_daily_r.to_numpy())

    wf2 = run_walk_forward(bars, strategy, costs.scaled(2.0), **wf_kwargs)
    m2 = trade_metrics(wf2.oos_trades, span_years)

    rw = random_walk_test(bars, strategy, costs, n_runs=n_random, **wf_kwargs) if n_random else None

    accounts = {}
    for size in account_sizes:
        a = simulate_account(oos, costs, size, risk_pct=risk_pct, max_risk_pct=2 * risk_pct)
        forced = simulate_account(oos, costs, size, risk_pct=risk_pct, max_risk_pct=1.0)
        accounts[str(size)] = {
            "capped_risk": {k: v for k, v in a.items() if k != "curve"},
            "forced_min_lot": {k: v for k, v in forced.items() if k != "curve"},
        }

    oos_bars = bars[bars.index >= wf.folds[0].test_start] if wf.folds else bars
    buy_hold_pct = float((oos_bars["close"].iloc[-1] / oos_bars["close"].iloc[0] - 1) * 100)

    checks = {
        "no_lookahead": lookahead_ok,
        "enough_oos_trades (>=100)": m["trades"] >= 100,
        "profitable_after_costs (avg R > 0, t > 2)": m["avg_r"] > 0 and m["t_stat"] > 2,
        "survives_2x_costs": m2["total_r"] > 0,
        "deflated_sharpe >= 0.95 (all trials)": dsr_all["dsr"] >= 0.95,
        "pbo < 0.5": pbo["pbo"] < 0.5,
    }
    if rw:
        checks["harness_sane (shuffled data loses)"] = rw["mean_total_r"] < 0
        checks["beats 95% of shuffled runs"] = m["total_r"] > rw["total_r_p95"]

    return {
        "strategy": strategy.name,
        "configs_tried": wf.n_configs,
        "folds": len(wf.folds),
        "oos_start": str(wf.folds[0].test_start) if wf.folds else None,
        "oos_end": str(bars.index[-1]),
        "chosen_params": [str(c) for c in wf.chosen],
        "oos": m,
        "buy_and_hold_pct": buy_hold_pct,
        "oos_sharpe_annual": dsr["sharpe_per_period"] * math.sqrt(days_per_year),
        "deflated_sharpe": dsr,
        "deflated_sharpe_all_trials": dsr_all,
        "pbo": pbo,
        "oos_2x_costs": m2,
        "random_walk": rw,
        "accounts": accounts,
        "checks": checks,
        "verdict": "PASS" if all(checks.values()) else "FAIL",
        "_oos_trades": oos,
    }


def print_report(res: dict, symbol: str, tf: str, costs):
    con = Console(width=140)
    m, m2 = res["oos"], res["oos_2x_costs"]
    t = Table(title=f"Harness: {res['strategy']} on {symbol} {tf}  (OOS {res['oos_start'][:10]} -> {res['oos_end'][:10]})")
    t.add_column("Metric", style="cyan")
    t.add_column("Value", style="bold")
    t.add_row("Buy & hold over OOS", f"{res['buy_and_hold_pct']:+.1f}%")
    t.add_row("Configs tried / folds", f"{res['configs_tried']} / {res['folds']}")
    t.add_row("Cost model", f"spread {costs.spread_points:g} pts, slip {costs.slippage_points:g}, comm ${costs.commission_per_lot:g}/lot")
    t.add_row("OOS trades (per year)", f"{m['trades']} ({m['trades_per_year']:.0f})")
    t.add_row("Win rate", f"{m['win_rate_pct']:.1f}%")
    t.add_row("Avg net R / trade", f"{m['avg_r']:+.3f} R  (costs {m['avg_cost_r']:.3f} R)")
    t.add_row("Total net R", f"{m['total_r']:+.1f} R")
    t.add_row("Profit factor", f"{m['profit_factor']:.2f}")
    t.add_row("t-stat", f"{m['t_stat']:.2f}")
    t.add_row("OOS Sharpe (annual)", f"{res['oos_sharpe_annual']:.2f}")
    t.add_row("Deflated Sharpe (this run / all trials)",
              f"{res['deflated_sharpe']['dsr']:.3f} / {res['deflated_sharpe_all_trials']['dsr']:.3f}"
              f"  ({res['deflated_sharpe_all_trials']['n_trials']} trials)")
    t.add_row("PBO", f"{res['pbo']['pbo']:.2f}")
    t.add_row("2x costs: total R / avg R", f"{m2['total_r']:+.1f} / {m2['avg_r']:+.3f}")
    rw = res["random_walk"]
    if rw:
        t.add_row("Shuffled data: mean total R", f"{rw['mean_total_r']:+.1f} ({rw['profitable_runs']}/{rw['runs']} profitable, p95 {rw['total_r_p95']:+.1f})")
    con.print(t)

    a = Table(title="Account simulation on OOS trades (1% risk target; trading stops for good at a 10% drawdown)")
    for col in ["Start", "Mode", "Final", "Return", "Max DD", "Median risk", "Max risk", "Skipped", "Halted (10% DD)"]:
        a.add_column(col)
    for size, modes in res["accounts"].items():
        for mode, v in modes.items():
            a.add_row(f"${float(size):,.0f}", mode, f"${v['final_equity']:,.0f}", f"{v['return_pct']:+.1f}%",
                      f"{v['max_drawdown_pct']:.1f}%", f"{v['median_risk_pct']:.2f}%", f"{v['max_risk_pct']:.2f}%",
                      str(v["trades_skipped_min_lot"]), (v["halted_at"] or "-")[:10])
    con.print(a)

    c = Table(title=f"Checks -> {res['verdict']}")
    c.add_column("Check")
    c.add_column("Result")
    for k, v in res["checks"].items():
        c.add_row(k, "[green]PASS[/green]" if v else "[red]FAIL[/red]")
    con.print(c)


def main():
    p = argparse.ArgumentParser(description="Honest test harness")
    p.add_argument("--symbol", default="XAUUSD")
    p.add_argument("--timeframe", default="H1")
    p.add_argument("--strategy", default="ema_cross", choices=sorted(STRATEGIES) + ["meta_breakout", "meta_breakout_long", "meta_breakout_regime"])
    p.add_argument("--random-runs", type=int, default=20)
    p.add_argument("--accounts", type=float, nargs="+", default=[600, 3000])
    p.add_argument("--risk-pct", type=float, default=0.01)
    p.add_argument("--anchored", action="store_true", help="expanding training window")
    p.add_argument("--data-tag", default="", help="data file suffix, e.g. _2009 for the long history")
    p.add_argument("--train-years", type=float, default=2.0)
    p.add_argument("--test-months", type=int, default=3)
    args = p.parse_args()

    bars = load_bars(args.symbol, args.timeframe, tag=args.data_tag)
    costs = load_cost_model(args.symbol)
    if args.strategy.startswith("meta_breakout"):
        strategy = MetaLabelBreakout(costs, long_only=args.strategy == "meta_breakout_long",
                                     regime_features=args.strategy == "meta_breakout_regime")
    else:
        strategy = STRATEGIES[args.strategy]()
    wf_kwargs = dict(train_years=args.train_years, test_months=args.test_months, anchored=args.anchored)
    stem = f"{args.symbol}_{args.timeframe}{args.data_tag}_{args.strategy}{'_anchored' if args.anchored else ''}"
    res = evaluate(bars, strategy, costs, args.random_runs, args.accounts, args.risk_pct, wf_kwargs,
                   earlier_trials=prior_trials(args.symbol, stem))
    print_report(res, args.symbol, args.timeframe, costs)

    out = Path("reports/harness")
    out.mkdir(parents=True, exist_ok=True)
    res.pop("_oos_trades").to_csv(out / f"{stem}_oos_trades.csv", index=False)
    with open(out / f"{stem}.json", "w") as f:
        json.dump(res, f, indent=2, default=str)
    print(f"[Harness] Saved {out / (stem + '.json')}")


if __name__ == "__main__":
    main()

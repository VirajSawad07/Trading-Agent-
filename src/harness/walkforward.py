"""Purged, embargoed, rolling walk-forward evaluation.

For each fold: pick the configuration using only the training window, then grade it on the
next unseen test window. Slide forward and repeat. The out-of-sample (OOS) result is the
concatenation of every test window, which is what the strategy would have done live.

Purge: a training trade only counts if it closed before (test_start - embargo), so no trade
used for selection overlaps the test window.
Embargo: a gap between training and test so slow indicators / overlapping labels can't leak.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.harness.costs import CostModel
from src.harness.simulator import TRADE_COLUMNS, simulate
from src.harness.stats import daily_r


@dataclass
class Fold:
    train_start: pd.Timestamp
    train_end: pd.Timestamp  # exclusive, already embargoed
    test_start: pd.Timestamp
    test_end: pd.Timestamp   # exclusive


@dataclass
class WalkForwardResult:
    oos_trades: pd.DataFrame
    folds: list
    chosen: list               # params chosen per fold (None = no config qualified)
    config_daily_r: pd.DataFrame  # OOS-period daily R for every config (T x N), for PBO/DSR
    oos_daily_r: pd.Series
    n_configs: int
    extra: dict = field(default_factory=dict)


def make_folds(index: pd.DatetimeIndex, train_years: float, test_months: int, embargo: pd.Timedelta,
               anchored: bool = False) -> list:
    """Rolling: each training window is the last train_years. Anchored (expanding): training always
    starts at the first bar, so later folds learn from all history so far. Test windows are the same."""
    folds = []
    start = index[0]
    train_len = pd.DateOffset(months=int(round(train_years * 12)))
    test_start = start + train_len
    while test_start < index[-1]:
        test_end = test_start + pd.DateOffset(months=test_months)
        train_start = start if anchored else test_start - train_len
        folds.append(Fold(train_start, test_start - embargo, test_start, test_end))
        test_start = test_end
    return folds


def _score(trades: pd.DataFrame, min_trades: int) -> float:
    if len(trades) < min_trades:
        return -np.inf
    r = trades["r_net"].to_numpy()
    sd = r.std(ddof=1)
    return r.mean() / sd * np.sqrt(len(r)) if sd > 0 else -np.inf


def _between(trades, start, end, col="entry_time"):
    return trades[(trades[col] >= start) & (trades[col] < end)]


def _drop_overlaps(trades: pd.DataFrame) -> pd.DataFrame:
    """Fold boundaries can switch configs mid-trade; keep only one open position at a time."""
    keep, last_exit = [], None
    for i, t in enumerate(trades.itertuples(index=False)):
        if last_exit is None or t.entry_time >= last_exit:
            keep.append(i)
            last_exit = t.exit_time
    return trades.iloc[keep].reset_index(drop=True)


def run_walk_forward(
    bars: pd.DataFrame,
    strategy,
    costs: CostModel,
    train_years: float = 2.0,
    test_months: int = 3,
    embargo_bars: int = 24,
    min_train_trades: int = 30,
    max_hold_bars: int = 240,
    min_val_trades: int = 10,
    anchored: bool = False,
) -> WalkForwardResult:
    """min_train_trades applies to rule strategies scored on the whole training window;
    min_val_trades to trainable strategies scored on the shorter (20%) validation slice."""
    bar_delta = pd.Series(bars.index).diff().median()
    embargo = bar_delta * embargo_bars
    folds = make_folds(bars.index, train_years, test_months, embargo, anchored)
    grid = strategy.param_grid()

    trainable = getattr(strategy, "trainable", False)
    min_trades = min_val_trades if trainable else min_train_trades
    if trainable:
        per_fold = _trainable_fold_trades(bars, strategy, costs, folds, grid, embargo, max_hold_bars)
    else:
        # A fixed rule is causal, so one full-history simulation per config can be sliced per window.
        full = [simulate(bars, strategy.signals(bars, p), costs, max_hold_bars) for p in grid]
        per_fold = [
            ([full[k][(full[k]["entry_time"] >= f.train_start) & (full[k]["exit_time"] < f.train_end)]
              for k in range(len(grid))],
             [_between(full[k], f.test_start, f.test_end) for k in range(len(grid))])
            for f in folds
        ]

    chosen, pieces = [], []
    for (train_trades, test_trades) in per_fold:
        scores = [_score(t, min_trades) for t in train_trades]
        best = int(np.argmax(scores))
        if not np.isfinite(scores[best]):
            chosen.append(None)
            continue
        chosen.append(grid[best])
        pieces.append(test_trades[best])

    oos = pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame(columns=TRADE_COLUMNS)
    oos = _drop_overlaps(oos.sort_values("entry_time").reset_index(drop=True)) if len(oos) else oos

    oos_start = folds[0].test_start if folds else bars.index[-1]
    days = pd.DatetimeIndex(sorted(set(bars.index[bars.index >= oos_start].normalize())))
    config_daily = pd.DataFrame({
        k: daily_r(pd.concat([pf[1][k] for pf in per_fold], ignore_index=True), days)
        for k in range(len(grid))
    })
    return WalkForwardResult(oos, folds, chosen, config_daily, daily_r(oos, days), len(grid))


def _val_trades(bars, strategy, costs, f, p, embargo, horizon, max_hold_bars):
    """Fit on the first 80% of the fold's training window; return trades in the purged last 20%."""
    val_start = f.train_start + (f.train_end - f.train_start) * 0.8
    fit_bars = bars[(bars.index >= f.train_start) & (bars.index < val_start - horizon - embargo)]
    upto_val = bars[(bars.index >= f.train_start) & (bars.index < f.train_end)]
    m = strategy.fit(fit_bars, p)
    t = simulate(upto_val, strategy.signals(upto_val, p, m), costs, max_hold_bars)
    return t[(t["entry_time"] >= val_start) & (t["exit_time"] < f.train_end)]


def _trainable_fold_trades(bars, strategy, costs, folds, grid, embargo, max_hold_bars):
    """Fit on the first 80% of the training window, validate on the purged last 20% to choose a
    config, then refit that config on the whole training window before the test."""
    horizon = pd.Series(bars.index).diff().median() * strategy.label_horizon_bars
    out = []
    for f in folds:
        full_train = bars[(bars.index >= f.train_start) & (bars.index < f.train_end - horizon)]
        upto_test = bars[(bars.index >= f.train_start) & (bars.index < f.test_end)]
        val_trades, test_trades = [], []
        for p in grid:
            val_trades.append(_val_trades(bars, strategy, costs, f, p, embargo, horizon, max_hold_bars))
            m = strategy.fit(full_train, p)
            t = simulate(upto_test, strategy.signals(upto_test, p, m), costs, max_hold_bars)
            test_trades.append(_between(t, f.test_start, f.test_end))
        out.append((val_trades, test_trades))
    return out


def fit_for_live(bars, strategy, costs, anchored: bool = True, train_years: float = 2.0,
                 embargo_bars: int = 24, max_hold_bars: int = 240, min_val_trades: int = 10):
    """Choose a config and fit its model exactly as a walk-forward fold whose test window
    starts right after the last bar would. Returns (params, model); (None, None) means no
    config qualified, so the live strategy should take no trades until the next refit."""
    bar_delta = pd.Series(bars.index).diff().median()
    embargo = bar_delta * embargo_bars
    horizon = bar_delta * strategy.label_horizon_bars
    test_start = bars.index[-1] + bar_delta
    train_start = bars.index[0] if anchored else test_start - pd.DateOffset(months=int(round(train_years * 12)))
    f = Fold(train_start, test_start - embargo, test_start, test_start)
    grid = strategy.param_grid()
    scores = [_score(_val_trades(bars, strategy, costs, f, p, embargo, horizon, max_hold_bars), min_val_trades)
              for p in grid]
    best = int(np.argmax(scores))
    if not np.isfinite(scores[best]):
        return None, None
    full_train = bars[(bars.index >= f.train_start) & (bars.index < f.train_end - horizon)]
    return grid[best], strategy.fit(full_train, grid[best])


def check_no_lookahead(bars: pd.DataFrame, strategy, params: dict, n_checks: int = 5, model=None) -> bool:
    """Signals computed on truncated history must equal signals computed on the full history.
    If they differ, the strategy peeks at future bars."""
    full = strategy.signals(bars, params, model)
    cuts = np.linspace(len(bars) // 2, len(bars) - 1, n_checks).astype(int)
    for cut in cuts:
        part = strategy.signals(bars.iloc[: cut + 1], params, model)
        a = full.iloc[: cut + 1]
        if not (a["signal"].to_numpy() == part["signal"].to_numpy()).all():
            return False
        if not np.allclose(a["sl_dist"].to_numpy(), part["sl_dist"].to_numpy(), equal_nan=True):
            return False
    return True

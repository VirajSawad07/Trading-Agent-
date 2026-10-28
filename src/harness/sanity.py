"""Random-walk sanity test.

Shuffle the order of bars (keeping each bar's own shape and size) so any real pattern over
time is destroyed but volatility is kept. Run the identical walk-forward on it. With no edge
to find, the strategy must LOSE after costs. If it profits on noise, the harness or the
strategy is broken. The real result should also beat most shuffled runs.
"""

import numpy as np
import pandas as pd

from src.harness.walkforward import run_walk_forward


def shuffled_bars(bars: pd.DataFrame, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    prev_close = bars["close"].shift(1).bfill()
    rel = pd.DataFrame({
        "gap": bars["open"] / prev_close,
        "h": bars["high"] / bars["open"],
        "l": bars["low"] / bars["open"],
        "c": bars["close"] / bars["open"],
    }).to_numpy()
    rel = rel[rng.permutation(len(rel))]
    opens = np.empty(len(rel))
    closes = np.empty(len(rel))
    last = float(bars["close"].iloc[0])
    for i, (gap, _, _, c) in enumerate(rel):
        opens[i] = last * gap
        closes[i] = opens[i] * c
        last = closes[i]
    return pd.DataFrame({
        "open": opens, "high": opens * rel[:, 1], "low": opens * rel[:, 2], "close": closes,
    }, index=bars.index)


def random_walk_test(bars, strategy, costs, n_runs: int = 20, **wf_kwargs) -> dict:
    results = []
    for seed in range(n_runs):
        wf = run_walk_forward(shuffled_bars(bars, seed), strategy, costs, **wf_kwargs)
        r = wf.oos_trades["r_net"]
        results.append((len(r), float(r.sum()), float(r.mean()) if len(r) else 0.0))
    arr = np.array(results)
    return {
        "runs": n_runs,
        "mean_trades": float(arr[:, 0].mean()),
        "mean_total_r": float(arr[:, 1].mean()),
        "mean_avg_r": float(arr[:, 2].mean()),
        "profitable_runs": int((arr[:, 1] > 0).sum()),
        "total_r_p95": float(np.percentile(arr[:, 1], 95)),
        "total_r_all": arr[:, 1].round(2).tolist(),
    }

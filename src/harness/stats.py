"""Performance and overfitting statistics.

- trade_metrics: profit after costs, in R.
- deflated_sharpe: Bailey & Lopez de Prado (2014). Probability the true Sharpe is above zero
  after accounting for how many configurations were tried.
- pbo_cscv: Probability of Backtest Overfitting via Combinatorially Symmetric Cross-Validation
  (Bailey, Borwein, Lopez de Prado, Zhu 2015).
Implemented from the published formulas, not from reference code.
"""

from itertools import combinations

import numpy as np
import pandas as pd
from scipy import stats as sps

EULER_GAMMA = 0.5772156649015329


def trade_metrics(trades: pd.DataFrame, span_years: float) -> dict:
    n = len(trades)
    if n == 0:
        return {"trades": 0, "trades_per_year": 0.0, "win_rate_pct": 0.0, "avg_r": 0.0, "total_r": 0.0,
                "profit_factor": 0.0, "t_stat": 0.0, "avg_cost_r": 0.0, "avg_bars_held": 0.0}
    r = trades["r_net"].to_numpy()
    gains, losses = r[r > 0].sum(), -r[r <= 0].sum()
    std = r.std(ddof=1) if n > 1 else 0.0
    return {
        "trades": n,
        "trades_per_year": n / span_years if span_years > 0 else 0.0,
        "win_rate_pct": float((r > 0).mean() * 100),
        "avg_r": float(r.mean()),
        "total_r": float(r.sum()),
        "profit_factor": float(gains / losses) if losses > 0 else float("inf"),
        "t_stat": float(r.mean() / std * np.sqrt(n)) if std > 0 else 0.0,
        "avg_cost_r": float((trades["r_gross"] - trades["r_net"]).mean()),
        "avg_bars_held": float(trades["bars_held"].mean()),
    }


def daily_r(trades: pd.DataFrame, trading_days: pd.DatetimeIndex) -> pd.Series:
    """Net R realised per trading day (zero on days without exits)."""
    if len(trades) == 0:
        return pd.Series(0.0, index=trading_days)
    by_day = trades.groupby(pd.to_datetime(trades["exit_time"]).dt.normalize())["r_net"].sum()
    return by_day.reindex(trading_days, fill_value=0.0)


def sharpe(per_period: np.ndarray) -> float:
    per_period = np.asarray(per_period, float)
    sd = per_period.std(ddof=1)
    return float(per_period.mean() / sd) if sd > 0 else 0.0


def deflated_sharpe(per_period: np.ndarray, n_trials: int, trial_sharpes: np.ndarray) -> dict:
    """per_period: the selected strategy's returns (non-annualised).
    trial_sharpes: per-period Sharpe of every configuration tried."""
    x = np.asarray(per_period, float)
    t = len(x)
    sr = sharpe(x)
    skew = float(sps.skew(x))
    kurt = float(sps.kurtosis(x, fisher=False))
    if n_trials > 1:
        var_sr = float(np.var(trial_sharpes, ddof=1))
        z1 = sps.norm.ppf(1 - 1.0 / n_trials)
        z2 = sps.norm.ppf(1 - 1.0 / (n_trials * np.e))
        sr0 = np.sqrt(var_sr) * ((1 - EULER_GAMMA) * z1 + EULER_GAMMA * z2)
    else:
        sr0 = 0.0
    denom = np.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4 * sr ** 2))
    z = (sr - sr0) * np.sqrt(t - 1) / denom
    return {"sharpe_per_period": sr, "sharpe_threshold": float(sr0), "dsr": float(sps.norm.cdf(z)),
            "n_trials": n_trials}


def pbo_cscv(perf: np.ndarray, n_blocks: int = 16) -> dict:
    """perf: T x N matrix, rows = time periods, columns = configurations."""
    perf = np.asarray(perf, float)
    t, n = perf.shape
    if n < 2:
        return {"pbo": float("nan"), "combinations": 0}
    size = t // n_blocks
    blocks = perf[: size * n_blocks].reshape(n_blocks, size, n)
    s1, s2 = blocks.sum(axis=1), (blocks ** 2).sum(axis=1)  # per-block sums, n_blocks x N

    def block_sharpe(idx):
        cnt = size * len(idx)
        m = s1[idx].sum(axis=0) / cnt
        var = s2[idx].sum(axis=0) / cnt - m ** 2
        return m / np.sqrt(np.maximum(var, 1e-18))

    logits, oos_of_best = [], []
    all_idx = np.arange(n_blocks)
    for combo in combinations(range(n_blocks), n_blocks // 2):
        is_idx = np.array(combo)
        oos_idx = np.setdiff1d(all_idx, is_idx)
        sr_is, sr_oos = block_sharpe(is_idx), block_sharpe(oos_idx)
        best = int(np.argmax(sr_is))
        rank = (sr_oos < sr_oos[best]).sum() + 1  # 1 = worst, N = best
        w = rank / (n + 1)
        logits.append(np.log(w / (1 - w)))
        oos_of_best.append(sr_oos[best])
    logits = np.array(logits)
    return {
        "pbo": float((logits <= 0).mean()),
        "combinations": len(logits),
        "prob_oos_loss": float((np.array(oos_of_best) <= 0).mean()),
    }

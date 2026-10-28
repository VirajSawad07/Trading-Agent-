"""Strategies in the harness interface.

A harness strategy provides:
- name, param_grid(): every configuration that will be tried (counted as trials for DSR/PBO).
- signals(bars, params, model=None): DataFrame on bars.index with signal (1/-1/0), sl_dist, tp_dist.
  Must only use data up to each bar's close (checked by walkforward.check_no_lookahead).
- trainable: if True, also fit(bars, params) -> model, and label_horizon_bars for purging.
"""

from itertools import product

import pandas as pd

from src.features.indicators import calculate_atr, calculate_ema


def _bracket(signal: pd.Series, atr: pd.Series, sl_mult: float, tp_mult: float) -> pd.DataFrame:
    return pd.DataFrame({"signal": signal.astype(int), "sl_dist": sl_mult * atr, "tp_dist": tp_mult * atr})


class EMACross:
    """The project's existing baseline: fast/slow EMA crossover with ATR stop and target."""

    name = "ema_cross"
    trainable = False

    def param_grid(self):
        grid = product([10, 20, 30], [50, 100, 200], [1.5, 2.0, 3.0], [1.5, 3.0, 4.5])
        return [dict(fast=f, slow=s, sl_mult=a, tp_mult=b) for f, s, a, b in grid]

    def signals(self, bars, params, model=None):
        fast = calculate_ema(bars["close"], params["fast"])
        slow = calculate_ema(bars["close"], params["slow"])
        above = fast > slow
        prev = above.shift(1, fill_value=False)
        sig = pd.Series(0, index=bars.index)
        sig[above & ~prev] = 1
        sig[~above & prev] = -1
        sig.iloc[: params["slow"]] = 0  # EMA warm-up
        return _bracket(sig, calculate_atr(bars, 14), params["sl_mult"], params["tp_mult"])


class DonchianBreakout:
    """Close breaks the highest high / lowest low of the previous N bars."""

    name = "donchian_breakout"
    trainable = False

    def param_grid(self):
        grid = product([20, 50, 100], [1.5, 2.0, 3.0], [1.5, 3.0, 4.5])
        return [dict(lookback=n, sl_mult=a, tp_mult=b) for n, a, b in grid]

    def signals(self, bars, params, model=None):
        n = params["lookback"]
        upper = bars["high"].rolling(n).max().shift(1)
        lower = bars["low"].rolling(n).min().shift(1)
        up = bars["close"] > upper
        dn = bars["close"] < lower
        sig = pd.Series(0, index=bars.index)
        sig[up & ~up.shift(1, fill_value=False)] = 1
        sig[dn & ~dn.shift(1, fill_value=False)] = -1
        return _bracket(sig, calculate_atr(bars, 14), params["sl_mult"], params["tp_mult"])


class DonchianLong(DonchianBreakout):
    """Benchmark: breakout longs only, with the meta-model's fixed 2x/3x ATR bracket.
    If a model can't beat this, it is only riding gold's uptrend, not timing trades."""

    name = "donchian_long"

    def param_grid(self):
        return [dict(lookback=n, sl_mult=2.0, tp_mult=3.0) for n in (20, 50, 100)]

    def signals(self, bars, params, model=None):
        out = super().signals(bars, params)
        out["signal"] = out["signal"].clip(lower=0)
        return out


STRATEGIES = {s.name: s for s in (EMACross, DonchianBreakout, DonchianLong)}

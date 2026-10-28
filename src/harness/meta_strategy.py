"""Meta-labeling on top of the Donchian breakout (Lopez de Prado, AFML ch. 3).

The breakout rule proposes trades. A LightGBM classifier, trained only on past signals,
estimates the probability each proposed trade ends in profit after costs, and the trade is
taken only if that probability clears a threshold. The model never picks direction.

Labels come from grading each training signal as its own trade with the harness simulator,
using only bars inside the fit window; trades still open at the window's end are dropped,
so no label can use data from the validation or test period.

The stop/target (2x / 3x ATR) are the project's original defaults, fixed before any
harness run, so they are not tuned on test results.
"""

from itertools import product

import lightgbm as lgb
import numpy as np
import pandas as pd

from src.features.indicators import calculate_adx, calculate_atr, calculate_ema, calculate_rsi
from src.harness.costs import CostModel
from src.harness.simulator import simulate
from src.harness.strategies import DonchianBreakout

SL_MULT, TP_MULT = 2.0, 3.0
MIN_TRAIN_SIGNALS = 60

FEATURES = [
    "direction", "strength", "ret_1", "ret_5", "ret_20", "ret_100", "atr_ratio", "vol_regime",
    "dist_ema_50", "dist_ema_200", "adx", "di_spread", "rsi", "range_pos_100", "vol_ratio",
    "hour", "weekday",
]

# Sideways-market detectors: losses cluster in choppy years, so let the model see chop.
REGIME_FEATURES = ["er_20", "er_100", "chop_14", "chop_100", "ema200_slope", "atr_pctile"]


def _efficiency_ratio(close: pd.Series, n: int) -> pd.Series:
    """Kaufman: net move / total path length over n bars. ~1 = clean trend, ~0 = chop."""
    return (close - close.shift(n)).abs() / close.diff().abs().rolling(n).sum()


def _choppiness(bars: pd.DataFrame, n: int) -> pd.Series:
    """Choppiness index: high (~60+) when price wanders inside a range, low when trending."""
    tr = pd.concat([bars["high"] - bars["low"], (bars["high"] - bars["close"].shift()).abs(),
                    (bars["low"] - bars["close"].shift()).abs()], axis=1).max(axis=1)
    rng = bars["high"].rolling(n).max() - bars["low"].rolling(n).min()
    return 100 * np.log10(tr.rolling(n).sum() / rng) / np.log10(n)


def _key(bars: pd.DataFrame, lookback: int) -> tuple:
    # Shuffled sanity data shares the index, so the prices are part of the key.
    return (len(bars), bars.index[0], bars.index[-1], float(bars["close"].sum()), lookback)


def signal_features(bars: pd.DataFrame, primary: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """Point-in-time features for every bar (only data up to that bar's close)."""
    close = bars["close"]
    atr = calculate_atr(bars, 14)
    adx = calculate_adx(bars, 14)
    upper = bars["high"].rolling(lookback).max().shift(1)
    lower = bars["low"].rolling(lookback).min().shift(1)
    d = primary["signal"]
    hi100, lo100 = bars["high"].rolling(100).max(), bars["low"].rolling(100).min()
    atr_ratio = atr / close
    ema200 = calculate_ema(close, 200)
    return pd.DataFrame({
        "er_20": _efficiency_ratio(close, 20),
        "er_100": _efficiency_ratio(close, 100),
        "chop_14": _choppiness(bars, 14),
        "chop_100": _choppiness(bars, 100),
        "ema200_slope": (ema200 - ema200.shift(50)) / atr,
        "atr_pctile": atr_ratio.rolling(2000, min_periods=500).rank(pct=True),
        "direction": d,
        "strength": np.where(d > 0, close - upper, lower - close) / atr,
        "ret_1": np.log(close / close.shift(1)),
        "ret_5": np.log(close / close.shift(5)),
        "ret_20": np.log(close / close.shift(20)),
        "ret_100": np.log(close / close.shift(100)),
        "atr_ratio": atr_ratio,
        "vol_regime": atr_ratio / atr_ratio.rolling(500, min_periods=100).median(),
        "dist_ema_50": (close - calculate_ema(close, 50)) / atr,
        "dist_ema_200": (close - calculate_ema(close, 200)) / atr,
        "adx": adx["adx"],
        "di_spread": adx["plus_di"] - adx["minus_di"],
        "rsi": calculate_rsi(close, 14),
        "range_pos_100": (close - lo100) / (hi100 - lo100),
        "vol_ratio": bars["volume"] / bars["volume"].rolling(20).mean() if "volume" in bars else 1.0,
        "hour": bars.index.hour,  # broker server time; only used as a learned category
        "weekday": bars.index.day_of_week,
    }, index=bars.index)


class _Model:
    def __init__(self, clf=None):
        self.clf = clf  # None = not enough training data -> take no trades


class MetaLabelBreakout:
    name = "meta_breakout"
    trainable = True
    label_horizon_bars = 0  # labels are confined to the fit window (see module docstring)

    def __init__(self, costs: CostModel, max_hold_bars: int = 240, long_only: bool = False,
                 regime_features: bool = False):
        self.costs = costs
        self.max_hold_bars = max_hold_bars
        self.long_only = long_only
        self.features = FEATURES + (REGIME_FEATURES if regime_features else [])
        if long_only:
            self.name = "meta_breakout_long"
        elif regime_features:
            self.name = "meta_breakout_regime"
        # The fitted model and features depend on lookback, not on threshold: cache them.
        self._fits, self._feats = {}, {}

    def param_grid(self):
        return [dict(lookback=n, threshold=t) for n, t in product([20, 50, 100], [0.50, 0.55, 0.60])]

    def _primary(self, bars, params):
        p = dict(lookback=params["lookback"], sl_mult=SL_MULT, tp_mult=TP_MULT)
        sig = DonchianBreakout().signals(bars, p)
        if self.long_only:
            sig["signal"] = sig["signal"].clip(lower=0)
        return sig

    def _features(self, bars, primary, lookback):
        key = _key(bars, lookback)
        if key not in self._feats:
            if len(self._feats) > 64:
                self._feats.clear()
            self._feats[key] = signal_features(bars, primary, lookback)[self.features]
        return self._feats[key]

    def fit(self, bars, params):
        key = _key(bars, params["lookback"])
        if key not in self._fits:
            if len(self._fits) > 256:
                self._fits.clear()
            self._fits[key] = self._fit(bars, params)
        return self._fits[key]

    def _fit(self, bars, params):
        primary = self._primary(bars, params)
        graded = simulate(bars, primary, self.costs, self.max_hold_bars, independent=True)
        graded = graded[~graded["exit_reason"].isin(["END"])]
        if len(graded) < MIN_TRAIN_SIGNALS:
            return _Model()
        X = self._features(bars, primary, params["lookback"]).loc[graded["signal_time"]]
        y = (graded["r_net"].to_numpy() > 0).astype(int)
        if y.min() == y.max():
            return _Model()
        clf = lgb.LGBMClassifier(
            n_estimators=200, learning_rate=0.03, num_leaves=7, min_child_samples=20,
            subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
            random_state=0, verbose=-1,
        )
        clf.fit(X, y)
        return _Model(clf)

    def signals(self, bars, params, model=None):
        primary = self._primary(bars, params)
        if model is None:
            return primary  # unfiltered (used only for structural checks)
        out = primary.copy()
        idx = primary.index[primary["signal"] != 0]
        if model.clf is None or len(idx) == 0:
            out["signal"] = 0
            return out
        X = self._features(bars, primary, params["lookback"]).loc[idx]
        prob = model.clf.predict_proba(X)[:, 1]
        out.loc[idx[prob < params["threshold"]], "signal"] = 0
        return out

    def explain_last(self, bars, params, model) -> dict:
        """The decision for the last bar, with what went into it (for the live decision ledger).
        Same rule as signals(): the breakout is taken only if the model's probability clears
        the threshold."""
        n = params["lookback"]
        primary = self._primary(bars, params)
        last = primary.iloc[-1]
        upper = float(bars["high"].iloc[-n - 1:-1].max())
        lower = float(bars["low"].iloc[-n - 1:-1].min())
        prob = None
        if int(last["signal"]) != 0 and model is not None and model.clf is not None:
            X = self._features(bars, primary, n).iloc[[-1]]
            prob = float(model.clf.predict_proba(X)[0, 1])
        take = prob is not None and prob >= params["threshold"]
        return {
            "bar_time": str(bars.index[-1]), "close": float(bars["close"].iloc[-1]),
            "channel_high": upper, "channel_low": lower,
            "breakout": int(last["signal"]), "probability": prob, "threshold": params["threshold"],
            "signal": int(last["signal"]) if take else 0,
            "sl_dist": float(last["sl_dist"]), "tp_dist": float(last["tp_dist"]),
            "model_ready": model is not None and model.clf is not None,
        }

"""Advanced Quantitative Alpha Features & Predictive Target Engineering."""

from typing import List, Tuple
import numpy as np
import pandas as pd
from src.features.indicators import calculate_atr, calculate_bollinger_bands, calculate_ema, calculate_rsi


def compute_alpha_features(df: pd.DataFrame) -> pd.DataFrame:
    """Extracts stationary, point-in-time quantitative alpha features for ML modeling.
    
    All features are strictly normalized to prevent non-stationary price drift.
    """
    df = df.copy()
    close = df["close"]
    high = df["high"]
    low = df["low"]
    open_p = df["open"]
    volume = df["volume"]

    # 1. Multi-horizon log returns (Stationary momentum)
    df["return_1"] = np.log(close / close.shift(1))
    df["return_3"] = np.log(close / close.shift(3))
    df["return_5"] = np.log(close / close.shift(5))
    df["return_10"] = np.log(close / close.shift(10))
    df["return_20"] = np.log(close / close.shift(20))

    # 2. Volatility & ATR features
    atr = calculate_atr(df, period=14)
    df["atr_ratio"] = atr / (close + 1e-9)
    
    bb = calculate_bollinger_bands(close, period=20, num_std=2.0)
    df["bb_bandwidth"] = bb["bb_bandwidth"]
    df["bb_position"] = (close - bb["bb_lower"]) / (bb["bb_upper"] - bb["bb_lower"] + 1e-9)

    # 3. Normalized Distance from Moving Averages (Trend extension)
    ema_20 = calculate_ema(close, 20)
    ema_50 = calculate_ema(close, 50)
    df["dist_ema_20"] = (close - ema_20) / (atr + 1e-9)
    df["dist_ema_50"] = (close - ema_50) / (atr + 1e-9)
    df["ema_diff_ratio"] = (ema_20 - ema_50) / (atr + 1e-9)

    # 4. Momentum & Oscillators
    df["rsi_14"] = calculate_rsi(close, 14) / 100.0  # Normalized to [0, 1]
    
    # MACD normalized by ATR
    ema_12 = calculate_ema(close, 12)
    ema_26 = calculate_ema(close, 26)
    macd = ema_12 - ema_26
    macd_signal = calculate_ema(macd, 9)
    df["macd_hist_atr"] = (macd - macd_signal) / (atr + 1e-9)

    # 5. Candlestick Anatomy & Price Action
    candle_range = high - low + 1e-9
    df["body_ratio"] = (close - open_p).abs() / candle_range
    df["upper_wick_ratio"] = (high - np.maximum(close, open_p)) / candle_range
    df["lower_wick_ratio"] = (np.minimum(close, open_p) - low) / candle_range

    # 6. Volume Dynamics
    vol_ma_20 = volume.rolling(window=20).mean()
    df["vol_ratio"] = volume / (vol_ma_20 + 1e-9)

    # 7. Session Time-of-Day Features
    if not isinstance(df.index, pd.DatetimeIndex):
        if "time" in df.columns:
            df["time"] = pd.to_datetime(df["time"])
            df = df.set_index("time")

    hours = df.index.hour
    df["is_asian"] = ((hours >= 0) & (hours < 8)).astype(int)
    df["is_london"] = ((hours >= 7) & (hours < 15)).astype(int)
    df["is_newyork"] = ((hours >= 12) & (hours < 20)).astype(int)
    df["is_ny_london_overlap"] = ((hours >= 12) & (hours < 15)).astype(int)

    return df


def get_feature_columns() -> List[str]:
    """Returns list of active feature names used for model input."""
    return [
        "return_1",
        "return_3",
        "return_5",
        "return_10",
        "return_20",
        "atr_ratio",
        "bb_bandwidth",
        "bb_position",
        "dist_ema_20",
        "dist_ema_50",
        "ema_diff_ratio",
        "rsi_14",
        "macd_hist_atr",
        "body_ratio",
        "upper_wick_ratio",
        "lower_wick_ratio",
        "vol_ratio",
        "is_asian",
        "is_london",
        "is_newyork",
        "is_ny_london_overlap",
    ]


def create_ml_dataset(
    df: pd.DataFrame, horizon_bars: int = 8, threshold_pct: float = 0.002
) -> Tuple[pd.DataFrame, pd.Series]:
    """Builds features and target labels with strict point-in-time alignment.
    
    Target:
    - 1: BUY  (forward return > +threshold_pct)
    - 2: SELL (forward return < -threshold_pct)
    - 0: HOLD / NOISE (within [-threshold_pct, +threshold_pct])
    """
    featured_df = compute_alpha_features(df)
    features = get_feature_columns()

    # Forward return calculation: shift(-horizon_bars) looks ahead strictly for target creation
    future_close = featured_df["close"].shift(-horizon_bars)
    forward_return = (future_close - featured_df["close"]) / featured_df["close"]

    target = pd.Series(0, index=featured_df.index)
    target[forward_return > threshold_pct] = 1
    target[forward_return < -threshold_pct] = 2

    # Drop the trailing NaN bars where future prices are unknown
    valid_mask = ~forward_return.isna()
    valid_features = featured_df.loc[valid_mask, features].dropna()
    valid_target = target.loc[valid_features.index]

    return valid_features, valid_target

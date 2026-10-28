"""Technical Indicator and Feature Engineering Pipeline."""

import numpy as np
import pandas as pd


def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    """Calculates Exponential Moving Average (EMA)."""
    return series.ewm(span=period, adjust=False).mean()


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculates Average True Range (ATR).
    
    ATR = EMA of True Range, where:
    TR = max(High - Low, abs(High - Close_prev), abs(Low - Close_prev))
    """
    high = df["high"]
    low = df["low"]
    close_prev = df["close"].shift(1)

    tr1 = high - low
    tr2 = (high - close_prev).abs()
    tr3 = (low - close_prev).abs()

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    # Using Wilder's smoothing / EMA for ATR
    atr = tr.ewm(alpha=1.0 / period, adjust=False).mean()
    return atr


def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Calculates Relative Strength Index (RSI)."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()

    rs = avg_gain / (avg_loss + 1e-9)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi


def calculate_bollinger_bands(
    series: pd.Series, period: int = 20, num_std: float = 2.0
) -> pd.DataFrame:
    """Calculates Bollinger Bands (Middle, Upper, Lower, Bandwidth)."""
    middle = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    upper = middle + (std * num_std)
    lower = middle - (std * num_std)
    bandwidth = (upper - lower) / (middle + 1e-9)

    return pd.DataFrame(
        {
            "bb_middle": middle,
            "bb_upper": upper,
            "bb_lower": lower,
            "bb_bandwidth": bandwidth,
        },
        index=series.index,
    )


def calculate_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Calculates Average Directional Index (ADX) and +DI / -DI directional indicators."""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_close = close.shift(1)

    # Directional Movement
    up_move = high - prev_high
    down_move = prev_low - low

    plus_dm = pd.Series(0.0, index=df.index)
    minus_dm = pd.Series(0.0, index=df.index)

    plus_cond = (up_move > down_move) & (up_move > 0)
    minus_cond = (down_move > up_move) & (down_move > 0)

    plus_dm[plus_cond] = up_move[plus_cond]
    minus_dm[minus_cond] = down_move[minus_cond]

    # True Range
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Smooth with Wilder's EMA
    tr_smooth = tr.ewm(alpha=1.0 / period, adjust=False).mean()
    plus_di = 100.0 * (plus_dm.ewm(alpha=1.0 / period, adjust=False).mean() / (tr_smooth + 1e-9))
    minus_di = 100.0 * (minus_dm.ewm(alpha=1.0 / period, adjust=False).mean() / (tr_smooth + 1e-9))

    dx = 100.0 * ((plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9))
    adx = dx.ewm(alpha=1.0 / period, adjust=False).mean()

    return pd.DataFrame({"adx": adx, "plus_di": plus_di, "minus_di": minus_di}, index=df.index)


def add_session_features(df: pd.DataFrame) -> pd.DataFrame:
    """Adds forex/commodities market session flags (UTC time).
    
    - Asian Session: 00:00 - 08:00 UTC (Tokyo/Sydney)
    - London Session: 07:00 - 15:00 UTC
    - New York Session: 12:00 - 20:00 UTC
    - NY/London Overlap: 12:00 - 15:00 UTC (Highest Gold liquidity and volatility)
    """
    df = df.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        if "time" in df.columns:
            df["time"] = pd.to_datetime(df["time"])
            df = df.set_index("time")

    hours = df.index.hour
    df["session_asian"] = ((hours >= 0) & (hours < 8)).astype(int)
    df["session_london"] = ((hours >= 7) & (hours < 15)).astype(int)
    df["session_newyork"] = ((hours >= 12) & (hours < 20)).astype(int)
    df["session_overlap"] = ((hours >= 12) & (hours < 15)).astype(int)
    return df


def generate_baseline_features(
    df: pd.DataFrame, fast_period: int = 20, slow_period: int = 50, atr_period: int = 14
) -> pd.DataFrame:
    """Computes all technical features required for the baseline strategy."""
    df = df.copy()
    df["ema_fast"] = calculate_ema(df["close"], fast_period)
    df["ema_slow"] = calculate_ema(df["close"], slow_period)
    df["atr"] = calculate_atr(df, atr_period)
    df["rsi"] = calculate_rsi(df["close"], period=14)
    
    bb = calculate_bollinger_bands(df["close"], period=20, num_std=2.0)
    df = pd.concat([df, bb], axis=1)
    
    df = add_session_features(df)
    return df

"""Unit tests for Technical Indicators and Feature Engineering."""

import numpy as np
import pandas as pd
import pytest
from src.features.indicators import (
    calculate_atr,
    calculate_bollinger_bands,
    calculate_ema,
    calculate_rsi,
    generate_baseline_features,
)


@pytest.fixture
def sample_ohlcv():
    dates = pd.date_range("2026-01-01", periods=100, freq="15min")
    np.random.seed(42)
    closes = 2600.0 + np.cumsum(np.random.normal(0, 1, 100))
    opens = closes + np.random.normal(0, 0.5, 100)
    highs = np.maximum(opens, closes) + np.random.uniform(0.5, 2.0, 100)
    lows = np.minimum(opens, closes) - np.random.uniform(0.5, 2.0, 100)
    volumes = np.random.randint(100, 1000, 100)

    df = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=dates,
    )
    return df


def test_calculate_ema(sample_ohlcv):
    ema = calculate_ema(sample_ohlcv["close"], period=20)
    assert len(ema) == len(sample_ohlcv)
    assert not ema.isna().any()


def test_calculate_atr(sample_ohlcv):
    atr = calculate_atr(sample_ohlcv, period=14)
    assert len(atr) == len(sample_ohlcv)
    assert (atr > 0).all()


def test_calculate_rsi(sample_ohlcv):
    rsi = calculate_rsi(sample_ohlcv["close"], period=14)
    assert len(rsi) == len(sample_ohlcv)
    valid_rsi = rsi.dropna()
    assert (valid_rsi >= 0).all() and (valid_rsi <= 100).all()


def test_calculate_bollinger_bands(sample_ohlcv):
    bb = calculate_bollinger_bands(sample_ohlcv["close"], period=20, num_std=2.0)
    assert "bb_upper" in bb.columns
    assert "bb_lower" in bb.columns
    valid_bb = bb.dropna()
    assert (valid_bb["bb_upper"] >= valid_bb["bb_lower"]).all()


def test_generate_baseline_features(sample_ohlcv):
    featured = generate_baseline_features(sample_ohlcv)
    assert "ema_fast" in featured.columns
    assert "ema_slow" in featured.columns
    assert "atr" in featured.columns
    assert "session_london" in featured.columns
    assert "session_newyork" in featured.columns

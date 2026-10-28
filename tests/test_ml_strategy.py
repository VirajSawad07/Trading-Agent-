"""Unit tests for Machine Learning Strategy Inference."""

import os
import numpy as np
import pandas as pd
import pytest
from src.strategies.ml_strategy import MLStrategy


@pytest.fixture
def dummy_candles():
    dates = pd.date_range("2026-02-01", periods=100, freq="15min")
    np.random.seed(42)
    closes = 2700.0 + np.cumsum(np.random.normal(0, 1.0, 100))
    opens = closes + np.random.normal(0, 0.3, 100)
    highs = np.maximum(opens, closes) + 1.0
    lows = np.minimum(opens, closes) - 1.0

    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": 500},
        index=dates,
    )


def test_ml_strategy_signal_generation(dummy_candles):
    model_path = "models/ml/lightgbm_gold_m15.pkl"
    if not os.path.exists(model_path):
        pytest.skip("Model artifact not yet trained.")

    strategy = MLStrategy(model_path=model_path, min_confidence=0.40)
    df_signals = strategy.generate_signals(dummy_candles)

    assert "signal" in df_signals.columns
    assert "prob_buy" in df_signals.columns
    assert "prob_sell" in df_signals.columns
    assert "sl_price" in df_signals.columns
    assert "tp_price" in df_signals.columns

    # Verify probability bounds
    assert (df_signals["prob_buy"] >= 0).all() and (df_signals["prob_buy"] <= 1).all()
    assert (df_signals["prob_sell"] >= 0).all() and (df_signals["prob_sell"] <= 1).all()

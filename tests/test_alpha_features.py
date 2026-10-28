"""Unit tests for Alpha Features and Target Engineering."""

import numpy as np
import pandas as pd
import pytest
from src.features.alpha_features import compute_alpha_features, create_ml_dataset, get_feature_columns


@pytest.fixture
def sample_data():
    dates = pd.date_range("2026-01-01", periods=150, freq="15min")
    np.random.seed(99)
    closes = 2650.0 + np.cumsum(np.random.normal(0, 1.5, 150))
    opens = closes + np.random.normal(0, 0.5, 150)
    highs = np.maximum(opens, closes) + np.random.uniform(0.5, 2.0, 150)
    lows = np.minimum(opens, closes) - np.random.uniform(0.5, 2.0, 150)
    volumes = np.random.randint(100, 2000, 150)

    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=dates,
    )


def test_compute_alpha_features(sample_data):
    df_feat = compute_alpha_features(sample_data)
    feature_cols = get_feature_columns()

    for col in feature_cols:
        assert col in df_feat.columns, f"Missing feature: {col}"

    # Check for no infinite values
    X = df_feat[feature_cols].dropna()
    assert not np.isinf(X.values).any()


def test_create_ml_dataset(sample_data):
    X, y = create_ml_dataset(sample_data, horizon_bars=5, threshold_pct=0.001)

    assert len(X) == len(y)
    assert len(X) > 0
    # Targets must only be 0 (HOLD), 1 (BUY), or 2 (SELL)
    assert set(y.unique()).issubset({0, 1, 2})

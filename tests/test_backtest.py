"""Unit tests for the Backtest Engine."""

import numpy as np
import pandas as pd
import pytest
from src.backtest.engine import BacktestEngine
from src.strategies.baseline_ema import BaselineEMAStrategy


@pytest.fixture
def sample_gold_df():
    dates = pd.date_range("2026-01-01", periods=200, freq="15min")
    np.random.seed(123)
    closes = 2650.0 + np.cumsum(np.random.normal(0.05, 1.2, 200))
    opens = closes + np.random.normal(0, 0.4, 200)
    highs = np.maximum(opens, closes) + np.random.uniform(0.5, 2.5, 200)
    lows = np.minimum(opens, closes) - np.random.uniform(0.5, 2.5, 200)

    df = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": 500},
        index=dates,
    )
    return df


def test_baseline_strategy_execution(sample_gold_df, tmp_path):
    strategy = BaselineEMAStrategy(fast_period=10, slow_period=20, filter_session=False)
    df_signals = strategy.generate_signals(sample_gold_df)

    assert "signal" in df_signals.columns
    assert "sl_price" in df_signals.columns
    assert "tp_price" in df_signals.columns

    # Setup temporary risk config for backtest
    config_file = tmp_path / "risk_limits.yaml"
    config_file.write_text(
        """
risk_limits:
  max_risk_per_trade_pct: 0.01
  max_daily_loss_pct: 0.05
  max_total_drawdown_pct: 0.15
  max_open_positions: 1
  max_spread_points: 50
  min_lot_size: 0.01
  max_lot_size: 2.0
  lot_step: 0.01
  demo_account_only: true
  enforce_stop_loss: true
"""
    )

    engine = BacktestEngine(
        initial_capital=10000.0,
        spread_points=20.0,
        commission_per_lot=7.0,
        risk_config_path=str(config_file),
    )

    results = engine.run(df_signals)
    metrics = results["metrics"]

    assert "total_net_profit" in metrics
    assert "win_rate_pct" in metrics
    assert "max_drawdown_pct" in metrics
    assert "sharpe_ratio" in metrics
    assert len(results["equity_curve"]) == len(sample_gold_df)

"""Unit tests for Specialized Multi-Agent System and Decision Coordinator."""

import numpy as np
import pandas as pd
import pytest
from src.agents.llm_agent import LLMAgent
from src.agents.quant_agent import QuantAgent
from src.agents.regime_agent import RegimeAgent
from src.orchestration.coordinator import DecisionCoordinator


@pytest.fixture
def trending_bull_data():
    dates = pd.date_range("2026-01-01", periods=100, freq="15min")
    # Strong upward trend
    closes = 2600.0 + np.linspace(0, 50, 100)
    opens = closes - 0.2
    highs = closes + 1.0
    lows = opens - 0.5

    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": 1000},
        index=dates,
    )


def test_regime_agent_trend_detection(trending_bull_data):
    agent = RegimeAgent(adx_trend_threshold=20.0)
    regime = agent.analyze(trending_bull_data)

    assert regime.regime == "TRENDING_BULL"
    assert regime.allow_buy is True
    assert regime.allow_sell is False
    assert regime.adx_value >= 20.0


def test_llm_agent_friday_close_lockout():
    agent = LLMAgent()
    # Friday 21:00 UTC
    friday_night = pd.Timestamp("2026-01-02 21:00:00")  # Jan 2, 2026 was a Friday
    context = agent.evaluate_context(current_time=friday_night, current_price=2650.0)

    assert context.veto_trade is True
    assert context.event_lockout is True
    assert "Friday market close" in context.reasoning


def test_coordinator_veto_on_conflict(trending_bull_data):
    coordinator = DecisionCoordinator()
    # Mock quant agent to want a SELL
    coordinator.quant_agent.model = None  # Ensure fallback

    decision = coordinator.arbitrate(trending_bull_data)
    assert decision.action == "HOLD"
    assert len(decision.audit_trail) > 0

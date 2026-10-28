"""Unit tests for the Deterministic Risk Engine."""

import pytest
from src.risk.risk_engine import AccountState, MarketConditions, OrderProposal, RiskEngine


@pytest.fixture
def risk_engine(tmp_path):
    # Create temporary config
    config_file = tmp_path / "risk_limits.yaml"
    config_file.write_text(
        """
risk_limits:
  max_risk_per_trade_pct: 0.01
  max_daily_loss_pct: 0.03
  max_total_drawdown_pct: 0.10
  max_open_positions: 1
  max_spread_points: 50
  min_lot_size: 0.01
  max_lot_size: 2.0
  lot_step: 0.01
  demo_account_only: true
  enforce_stop_loss: true
"""
    )
    return RiskEngine(config_path=str(config_file))


def test_calculate_lot_size(risk_engine):
    # Capital: $10,000, Risk: 1% = $100
    # Entry: $2,600, SL: $2,595 -> Distance: $5.00
    # Gold Contract Size: 100 -> $5.00 * 100 = $500 loss per 1.0 lot
    # Expected Lots = $100 / $500 = 0.20 lots
    lots = risk_engine.calculate_lot_size(
        equity=10000.0,
        entry_price=2600.0,
        stop_loss_price=2595.0,
        contract_size=100.0,
    )
    assert lots == 0.20


def test_reject_wide_spread(risk_engine):
    account = AccountState(balance=10000.0, equity=10000.0, open_positions=0, daily_starting_equity=10000.0, is_demo=True)
    market = MarketConditions(current_spread_points=65.0, bid=2600.0, ask=2600.65)  # 65 > 50 max
    proposal = OrderProposal(symbol="XAUUSD", action="BUY", entry_price=2600.0, stop_loss=2590.0, take_profit=2615.0)

    approved, reason, lots = risk_engine.validate_proposal(proposal, account, market)
    assert not approved
    assert "Spread too high" in reason


def test_reject_when_max_positions_reached(risk_engine):
    account = AccountState(balance=10000.0, equity=10000.0, open_positions=1, daily_starting_equity=10000.0, is_demo=True)
    market = MarketConditions(current_spread_points=20.0, bid=2600.0, ask=2600.20)
    proposal = OrderProposal(symbol="XAUUSD", action="BUY", entry_price=2600.0, stop_loss=2590.0, take_profit=2615.0)

    approved, reason, lots = risk_engine.validate_proposal(proposal, account, market)
    assert not approved
    assert "Max open positions reached" in reason


def test_kill_switch_on_daily_loss(risk_engine):
    # Daily loss = (10,000 - 9,600) / 10,000 = 4.0% > 3.0% limit
    account = AccountState(balance=9600.0, equity=9600.0, open_positions=0, daily_starting_equity=10000.0, is_demo=True)
    market = MarketConditions(current_spread_points=20.0, bid=2600.0, ask=2600.20)
    proposal = OrderProposal(symbol="XAUUSD", action="BUY", entry_price=2600.0, stop_loss=2590.0, take_profit=2615.0)

    approved, reason, lots = risk_engine.validate_proposal(proposal, account, market)
    assert not approved
    assert "Daily drawdown limit" in reason
    assert risk_engine.kill_switch_active


def test_block_live_account(risk_engine):
    account = AccountState(balance=10000.0, equity=10000.0, open_positions=0, daily_starting_equity=10000.0, is_demo=False)
    market = MarketConditions(current_spread_points=20.0, bid=2600.0, ask=2600.20)
    proposal = OrderProposal(symbol="XAUUSD", action="BUY", entry_price=2600.0, stop_loss=2590.0, take_profit=2615.0)

    approved, reason, lots = risk_engine.validate_proposal(proposal, account, market)
    assert not approved
    assert "Live account trade blocked" in reason
    assert risk_engine.kill_switch_active

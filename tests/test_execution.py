"""Unit tests for MT5 Demo Execution Gateway and Safety Interlocks."""

import pytest
from unittest.mock import MagicMock, patch
from src.execution.demo_gateway import DemoGateway, ExecutionResult
from src.risk.risk_engine import OrderProposal


def test_demo_gateway_blocks_live_account(tmp_path):
    config_file = tmp_path / "risk_limits.yaml"
    config_file.write_text(
        """
risk_limits:
  demo_account_only: true
"""
    )
    gateway = DemoGateway(risk_config_path=str(config_file))

    # Mock an MT5 account that is LIVE (trade_mode=2 instead of 0)
    mock_acc = MagicMock()
    mock_acc.login = 123456
    mock_acc.trade_mode = 2  # LIVE
    mock_acc.name = "Real Trader"
    mock_acc.server = "LiveServer"

    with patch("src.execution.demo_gateway.mt5.account_info", return_value=mock_acc):
        with pytest.raises(PermissionError) as exc_info:
            gateway.verify_demo_account()

        assert "SECURITY VIOLATION" in str(exc_info.value)
        assert "LIVE/CONTEST" in str(exc_info.value)


def test_demo_gateway_allows_demo_account(tmp_path):
    config_file = tmp_path / "risk_limits.yaml"
    config_file.write_text(
        """
risk_limits:
  demo_account_only: true
"""
    )
    gateway = DemoGateway(risk_config_path=str(config_file))

    # Mock an MT5 account that is DEMO (trade_mode=0)
    mock_acc = MagicMock()
    mock_acc.login = 999888
    mock_acc.trade_mode = 0  # DEMO
    mock_acc.name = "Demo Trader"
    mock_acc.server = "DemoServer"
    mock_acc.balance = 10000.0
    mock_acc.equity = 10000.0
    mock_acc.currency = "USD"

    with patch("src.execution.demo_gateway.mt5.account_info", return_value=mock_acc):
        info = gateway.verify_demo_account()
        assert info["is_demo"] is True
        assert info["login"] == 999888

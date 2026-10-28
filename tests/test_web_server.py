"""Unit and Integration Tests for Web Dashboard Server."""

import pytest
from fastapi.testclient import TestClient
from src.web.server import app

client = TestClient(app)


def test_dashboard_root_html():
    response = client.get("/")
    assert response.status_code == 200
    assert "AURA QUANT" in response.text
    assert "MT5 AI Quantitative Desk" in response.text


def test_api_status():
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert "connected" in data
    assert "balance" in data
    assert "equity" in data
    assert "floating_pnl" in data
    assert "open_positions" in data
    assert isinstance(data["open_positions"], list)


def test_api_market():
    response = client.get("/api/market")
    assert response.status_code == 200
    data = response.json()
    assert "symbols" in data
    assert isinstance(data["symbols"], dict)


def test_api_chart_data():
    response = client.get("/api/chart-data?symbol=XAUUSD&count=20")
    assert response.status_code == 200
    data = response.json()
    assert "symbol" in data
    assert "bars" in data
    assert len(data["bars"]) > 0
    bar = data["bars"][0]
    assert "open" in bar
    assert "high" in bar
    assert "low" in bar
    assert "close" in bar


def test_api_agent_deliberation():
    response = client.get("/api/agent-deliberation")
    assert response.status_code == 200
    data = response.json()
    assert "regime_agent" in data
    assert "quant_agent" in data
    assert "macro_agent" in data
    assert "consensus" in data
    assert data["consensus"]["action"] in ["BUY", "SELL", "HOLD"]


def test_api_history():
    response = client.get("/api/history")
    assert response.status_code == 200
    data = response.json()
    assert "deals" in data
    assert "total_realized_profit" in data


def test_api_toggle_mode():
    response = client.post("/api/toggle-mode", json={"mode": "micro_200"})
    assert response.status_code == 200
    assert response.json()["active_mode"] == "micro_200"

    response = client.post("/api/toggle-mode", json={"mode": "standard"})
    assert response.status_code == 200
    assert response.json()["active_mode"] == "standard"

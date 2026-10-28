import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from src.execution.demo_gateway import DemoGateway
from src.live.ledger import Ledger, read, verify
from src.live.paper_trader import bars_held, plan_actions
from src.risk.risk_engine import AccountState, MarketConditions, OrderProposal, RiskEngine
from tests.test_harness import GOLD, _trending_bars, make_bars


# ---------------------------------------------------------------- trade rules match the simulator

def test_plan_actions_mirror_simulator_rules():
    assert plan_actions(0, 0, 0) == []
    assert plan_actions(0, 0, 1) == [("open", 1)]
    assert plan_actions(1, 5, 1) == []                      # same-direction signal ignored
    assert plan_actions(1, 5, 0) == []
    assert plan_actions(1, 5, -1) == [("close", "REVERSE"), ("open", -1)]
    assert plan_actions(-1, 240, 0) == [("close", "TIME")]
    assert plan_actions(-1, 240, -1) == [("close", "TIME"), ("open", -1)]


def test_bars_held_counts_entry_bar():
    idx = pd.date_range("2026-01-05 10:00", periods=5, freq="h")
    assert bars_held(idx, pd.Timestamp("2026-01-05 10:00:07"), pd.Timedelta(hours=1)) == 5
    assert bars_held(idx, pd.Timestamp("2026-01-05 13:00:02"), pd.Timedelta(hours=1)) == 2


# ---------------------------------------------------------------- ledger

def test_ledger_chain_detects_tampering(tmp_path):
    path = tmp_path / "l.jsonl"
    led = Ledger(path)
    led.append("decision", "No breakout.", close=1.0)
    led.append("decision", "Breakout up.", close=2.0)
    assert verify(path) == (True, 2, "ok")

    Ledger(path).append("decision", "Third.")  # reopening continues the chain
    assert verify(path)[0] and read(path)[-1]["seq"] == 3

    lines = path.read_text().splitlines()
    rec = json.loads(lines[1])
    rec["close"] = 99.0
    lines[1] = json.dumps(rec)
    path.write_text("\n".join(lines) + "\n")
    ok, _, msg = verify(path)
    assert not ok and "record 2" in msg
    with pytest.raises(RuntimeError):
        Ledger(path)

    path.write_text("\n".join([lines[0], lines[2]]) + "\n")  # deleting a record also breaks it
    assert not verify(path)[0]


# ---------------------------------------------------------------- risk engine

@pytest.fixture
def engine(tmp_path):
    cfg = tmp_path / "r.yaml"
    cfg.write_text("risk_limits:\n  max_risk_per_trade_pct: 0.01\n  max_open_positions: 2\n  max_spread_points: 50\n"
                   "  max_total_drawdown_pct: 0.10\n  max_min_lot_risk_pct: 0.02\n")
    return RiskEngine(str(cfg))


def test_min_lot_only_when_risk_under_cap(engine):
    # Gold stop $28 away: 0.01 lots risks $28.
    lots = lambda eq: engine.calculate_lot_size(eq, 4000.0, 3972.0, 100.0)
    assert lots(600) == 0.0       # 4.7% > 2% cap: skip (no more blanket 0.01 for small accounts)
    assert lots(1500) == 0.01     # 1.9%: allowed
    assert lots(10000) == 0.03


def test_total_drawdown_from_peak_halts(engine):
    acct = AccountState(balance=2650, equity=2650, open_positions=0, daily_starting_equity=2650, peak_equity=3000)
    ok, why, _ = engine.validate_proposal(OrderProposal("XAUUSD", "BUY", 4000, 3990, 4015), acct,
                                          MarketConditions(30, 3999.7, 4000))
    assert not ok and "Total drawdown" in why and engine.kill_switch_active


def test_sizing_equity_is_separate_from_breakers(engine):
    acct = AccountState(balance=100000, equity=100000, open_positions=0, daily_starting_equity=100000)
    ok, _, lots = engine.validate_proposal(OrderProposal("XAUUSD", "BUY", 4000, 3990, 4015), acct,
                                           MarketConditions(30, 3999.7, 4000), 100.0, sizing_equity=3000)
    assert ok and lots == 0.03


# ---------------------------------------------------------------- gateway: no double fills

@pytest.fixture
def gw(tmp_path):
    cfg = tmp_path / "r.yaml"
    cfg.write_text("risk_limits:\n  demo_account_only: true\n")
    return DemoGateway(str(cfg), magic_number=777)


def _mt5(order_results, positions_seq):
    m = MagicMock()
    m.TRADE_RETCODE_DONE = 10009
    m.account_info.return_value = SimpleNamespace(trade_mode=0, login=1, name="d", server="s", balance=1, equity=1, currency="USD")
    m.ACCOUNT_TRADE_MODE_DEMO = 0
    m.symbol_info.return_value = SimpleNamespace(filling_mode=2, point=0.01)
    m.symbol_info_tick.return_value = SimpleNamespace(ask=4000.3, bid=4000.0)
    m.order_send.side_effect = order_results
    m.positions_get.side_effect = positions_seq
    return m


def _pos(tag, magic=777):
    return SimpleNamespace(ticket=42, comment=tag, magic=magic, volume=0.01, price_open=4000.3)


PROP = OrderProposal("XAUUSD", "BUY", 4000.3, 3990, 4015)


def test_existing_tagged_position_is_not_resent(gw):
    m = _mt5([], [[_pos("t1")]])
    with patch("src.execution.demo_gateway.mt5", m), patch("src.execution.demo_gateway.time.sleep"):
        r = gw.send_order(PROP, 0.01, client_tag="t1")
    assert r.success and r.ticket == 42 and m.order_send.call_count == 0


def test_non_retryable_reject_sends_once(gw):
    m = _mt5([SimpleNamespace(retcode=10019, comment="no money")], [[], []])
    with patch("src.execution.demo_gateway.mt5", m), patch("src.execution.demo_gateway.time.sleep"):
        r = gw.send_order(PROP, 0.01, client_tag="t1")
    assert not r.success and m.order_send.call_count == 1


def test_requote_is_retried(gw):
    m = _mt5([SimpleNamespace(retcode=10004, comment="requote"), SimpleNamespace(retcode=10009, order=7, price=4000.4)],
             [[], []])
    with patch("src.execution.demo_gateway.mt5", m), patch("src.execution.demo_gateway.time.sleep"):
        r = gw.send_order(PROP, 0.01, client_tag="t1")
    assert r.success and m.order_send.call_count == 2


def test_ambiguous_reply_checks_before_retry(gw):
    # No reply from the terminal, but the order did fill: must report it, never send again.
    m = _mt5([None], [[], [_pos("t1")]])
    with patch("src.execution.demo_gateway.mt5", m), patch("src.execution.demo_gateway.time.sleep"):
        r = gw.send_order(PROP, 0.01, client_tag="t1")
    assert r.success and m.order_send.call_count == 1


def test_other_magic_positions_are_invisible(gw):
    m = _mt5([], [[_pos("x", magic=1), _pos("y", magic=777)]])
    with patch("src.execution.demo_gateway.mt5", m):
        assert [p.comment for p in gw.bot_positions()] == ["y"]


# ---------------------------------------------------------------- live model == walk-forward model

def test_fit_for_live_matches_walk_forward_fold():
    from src.harness.meta_strategy import MetaLabelBreakout
    from src.harness.walkforward import fit_for_live, run_walk_forward
    bars = _trending_bars(9000)
    strat = MetaLabelBreakout(GOLD, regime_features=True)
    wf = run_walk_forward(bars, strat, GOLD, train_years=0.5, test_months=2, anchored=True)
    k = len(wf.folds) - 1
    params, _ = fit_for_live(bars[bars.index < wf.folds[k].test_start], MetaLabelBreakout(GOLD, regime_features=True),
                             GOLD, anchored=True)
    assert params == wf.chosen[k]


def test_explain_last_matches_signals():
    from src.harness.meta_strategy import MetaLabelBreakout
    bars = _trending_bars()
    strat = MetaLabelBreakout(GOLD, regime_features=True)
    p = dict(lookback=20, threshold=0.5)
    model = strat.fit(bars.iloc[:4000], p)
    sig = strat.signals(bars, p, model)
    checked = 0
    for end in np.flatnonzero(strat._primary(bars, p)["signal"].to_numpy() != 0)[-15:]:
        info = strat.explain_last(bars.iloc[: end + 1], p, model)
        assert info["signal"] == sig["signal"].iloc[end]
        assert info["breakout"] != 0
        checked += 1
    assert checked > 0


# ---------------------------------------------------------------- dashboard

def test_dashboard_view_reads_ledger_and_heartbeat(tmp_path):
    import os
    from src.live.dashboard import ledger_view
    led_path, state_path = tmp_path / "l.jsonl", tmp_path / "s.json"
    led = Ledger(led_path)
    led.append("session_start", "started")
    led.append("decision", "No breakout.", bar_time="2026-10-28 18:00:00", params={"lookback": 100, "threshold": 0.5})
    led.append("trade_closed", "Trade closed by take profit.", r_net=1.4, pnl_usd=42.0)
    led.append("trade_closed", "Trade closed by stop loss.", r_net=-1.05, pnl_usd=-31.5)
    state_path.write_text(json.dumps({"sizing_equity": 3000.0, "closed_pnl": 10.5}))

    v = ledger_view(led_path, state_path)
    assert v["running"] and v["ledger_ok"] and v["params"]["lookback"] == 100
    assert [p["cum_r"] for p in v["curve"]] == [1.4, pytest.approx(0.35)]
    assert v["summary"]["trades_closed"] == 2 and v["recent"][0]["event"] == "trade_closed"

    old = os.path.getmtime(state_path) - 600
    os.utime(state_path, (old, old))
    assert not ledger_view(led_path, state_path)["running"]  # no heartbeat for 10 min


def test_state_save_survives_a_busy_file(tmp_path, monkeypatch):
    from pathlib import Path
    from src.live.paper_trader import State
    path, calls = tmp_path / "s.json", {"n": 0}
    real = Path.replace

    def flaky(self, target):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError(5, "Access is denied")  # what Windows raises while a reader has it open
        return real(self, target)
    monkeypatch.setattr(Path, "replace", flaky)
    monkeypatch.setattr("src.live.paper_trader.time.sleep", lambda s: None)
    State(sizing_equity=100000.0).save(path)
    assert json.loads(path.read_text())["sizing_equity"] == 100000.0


def test_only_a_live_account_is_fatal():
    from src.execution.demo_gateway import LiveAccountError
    assert issubclass(LiveAccountError, PermissionError)  # old callers still catch it
    assert not isinstance(PermissionError(5, "Access is denied"), LiveAccountError)

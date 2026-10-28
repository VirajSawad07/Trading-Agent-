import numpy as np
import pandas as pd
import pytest

from src.harness.account import simulate_account
from src.harness.costs import CostModel
from src.harness.simulator import simulate
from src.harness.stats import deflated_sharpe, pbo_cscv
from src.harness.walkforward import check_no_lookahead, make_folds, run_walk_forward

ZERO = CostModel(contract_size=100, point=0.01, min_lot=0.01, lot_step=0.01, max_lot=100,
                 spread_points=0, slippage_points=0, commission_per_lot=0,
                 swap_long_points=0, swap_short_points=0)
GOLD = CostModel(contract_size=100, point=0.01, min_lot=0.01, lot_step=0.01, max_lot=100,
                 spread_points=35, slippage_points=5, commission_per_lot=7,
                 swap_long_points=-12.6, swap_short_points=-4.6)


def make_bars(rows, start="2024-01-02 10:00"):
    idx = pd.date_range(start, periods=len(rows), freq="h")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)


def one_signal(bars, at, direction, sl, tp):
    s = pd.DataFrame({"signal": 0, "sl_dist": sl, "tp_dist": tp}, index=bars.index)
    s.iloc[at, 0] = direction
    return s


def test_fills_at_next_open_and_hits_target():
    bars = make_bars([(100, 101, 99, 100), (102, 102.5, 101.5, 102), (102, 105, 101.9, 104)])
    t = simulate(bars, one_signal(bars, 0, 1, sl=2, tp=2), ZERO)
    assert len(t) == 1
    assert t.entry_price[0] == 102  # next bar's open, not the signal bar's close of 100
    assert t.exit_reason[0] == "TP" and t.r_net[0] == pytest.approx(1.0)


def test_stop_and_target_in_same_bar_counts_as_stop():
    bars = make_bars([(100, 100, 100, 100), (100, 100, 100, 100), (100, 103, 97, 100)])
    t = simulate(bars, one_signal(bars, 0, 1, sl=2, tp=2), ZERO)
    assert t.exit_reason[0] == "SL" and t.r_net[0] == pytest.approx(-1.0)


def test_gap_through_stop_fills_at_open():
    bars = make_bars([(100, 100, 100, 100), (100, 100.5, 99.5, 100), (95, 96, 94, 95)])
    t = simulate(bars, one_signal(bars, 0, 1, sl=2, tp=10), ZERO)
    assert t.exit_reason[0] == "SL_GAP" and t.r_net[0] == pytest.approx(-2.5)


def test_sell_pays_spread_on_exit():
    bars = make_bars([(100, 100, 100, 100), (100, 100.1, 99.9, 100), (99, 99.1, 97, 98)])
    t = simulate(bars, one_signal(bars, 0, -1, sl=2, tp=2), GOLD)
    # entry 100 - 0.05 slip = 99.95; target 97.95 needs ask (low + 0.35) <= 97.95
    assert t.exit_reason[0] == "TP"
    expected = (99.95 - 97.95 - 0.07) / 2
    assert t.r_net[0] == pytest.approx(expected)


def test_costs_make_random_trading_lose():
    rng = np.random.default_rng(0)
    n = 20000
    close = 2000 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    opens = np.concatenate([[2000], close[:-1]])
    hi = np.maximum(opens, close) * (1 + np.abs(rng.normal(0, 0.001, n)))
    lo = np.minimum(opens, close) * (1 - np.abs(rng.normal(0, 0.001, n)))
    bars = make_bars(list(zip(opens, hi, lo, close)))
    sig = pd.DataFrame({"signal": rng.choice([-1, 0, 0, 0, 1], n), "sl_dist": 8.0, "tp_dist": 8.0}, index=bars.index)
    t = simulate(bars, sig, GOLD)
    assert len(t) > 500
    assert t.r_net.mean() < 0
    assert simulate(bars, sig, ZERO).r_net.mean() == pytest.approx(0, abs=0.1)


class Peeker:
    name, trainable = "peeker", False

    def param_grid(self):
        return [{}]

    def signals(self, bars, params, model=None):
        nxt = bars["close"].shift(-1)  # looks at the future
        sig = np.sign(nxt - bars["close"]).fillna(0).astype(int)
        return pd.DataFrame({"signal": sig, "sl_dist": 1.0, "tp_dist": 1.0}, index=bars.index)


class Honest(Peeker):
    def signals(self, bars, params, model=None):
        sig = np.sign(bars["close"] - bars["close"].shift(1)).fillna(0).astype(int)
        return pd.DataFrame({"signal": sig, "sl_dist": 1.0, "tp_dist": 1.0}, index=bars.index)


def test_lookahead_check_catches_peeking():
    rng = np.random.default_rng(1)
    c = 100 + np.cumsum(rng.normal(0, 1, 500))
    bars = make_bars(list(zip(c, c + 1, c - 1, c)))
    assert not check_no_lookahead(bars, Peeker(), {})
    assert check_no_lookahead(bars, Honest(), {})


def test_folds_never_overlap_test_window():
    idx = pd.date_range("2021-01-01", "2026-01-01", freq="h")
    folds = make_folds(idx, 2.0, 3, pd.Timedelta(hours=24))
    assert len(folds) > 10
    for f in folds:
        assert f.train_end < f.test_start
        assert f.test_start < f.test_end
    for a, b in zip(folds, folds[1:]):
        assert a.test_end == b.test_start


def test_walk_forward_runs_and_reports_all_configs():
    rng = np.random.default_rng(2)
    n = 3 * 365 * 24
    c = 2000 + np.cumsum(rng.normal(0, 2, n))
    bars = make_bars(list(zip(c, c + 2, c - 2, c)), start="2021-01-01")

    class Rand(Honest):
        def param_grid(self):
            return [{"seed": s} for s in range(4)]

        def signals(self, bars, params, model=None):
            r = np.random.default_rng(params["seed"]).choice([-1, 0, 0, 0, 0, 0, 1], len(bars))
            return pd.DataFrame({"signal": r, "sl_dist": 4.0, "tp_dist": 4.0}, index=bars.index)

    wf = run_walk_forward(bars, Rand(), GOLD, train_years=1.0, test_months=3)
    assert wf.config_daily_r.shape[1] == 4
    assert len(wf.oos_trades) > 0
    assert (wf.oos_trades.entry_time >= wf.folds[0].test_start).all()


def test_pbo_flags_noise_and_clears_real_edge():
    rng = np.random.default_rng(3)
    noise = rng.normal(0, 1, (1600, 20))
    # IS and OOS halves come from one fixed sample, so picking the IS winner on noise
    # tends to land below the OOS median: PBO above 0.5 means "overfit".
    assert pbo_cscv(noise)["pbo"] > 0.5
    edge = noise.copy()
    edge[:, 0] += 0.3
    assert pbo_cscv(edge)["pbo"] < 0.1


def test_more_trials_deflate_sharpe():
    rng = np.random.default_rng(4)
    x = rng.normal(0.05, 1, 1000)
    trials = rng.normal(0, 0.03, 200)
    assert deflated_sharpe(x, 200, trials)["dsr"] < deflated_sharpe(x, 1, trials[:1])["dsr"]


def test_min_lot_overrisk_is_skipped_or_flagged():
    trades = pd.DataFrame({"exit_time": pd.date_range("2024-01-01", periods=3, freq="D"),
                           "sl_dist": [28.0] * 3, "r_net": [1.0, -1.0, 1.0]})
    capped = simulate_account(trades, GOLD, 600, risk_pct=0.01, max_risk_pct=0.02)
    assert capped["trades_taken"] == 0 and capped["trades_skipped_min_lot"] == 3
    forced = simulate_account(trades, GOLD, 600, risk_pct=0.01, max_risk_pct=1.0)
    assert forced["max_risk_pct"] == pytest.approx(28 / 600 * 100, rel=0.05)


def _trending_bars(n=6000, seed=5):
    rng = np.random.default_rng(seed)
    c = 2000 * np.exp(np.cumsum(rng.normal(0.0001, 0.003, n)))
    o = np.concatenate([[2000], c[:-1]])
    bars = make_bars(list(zip(o, np.maximum(o, c) * 1.001, np.minimum(o, c) * 0.999, c)), start="2022-01-03")
    bars["volume"] = 1000
    return bars


def test_independent_mode_grades_every_signal():
    bars = _trending_bars(2000)
    from src.harness.strategies import DonchianBreakout
    sig = DonchianBreakout().signals(bars, dict(lookback=20, sl_mult=2.0, tp_mult=3.0))
    n_signals = int((sig["signal"].iloc[:-1] != 0).sum())
    assert len(simulate(bars, sig, GOLD, independent=True)) == n_signals
    assert len(simulate(bars, sig, GOLD)) < n_signals


def test_meta_strategy_has_no_lookahead_and_filters_signals():
    from src.harness.meta_strategy import MetaLabelBreakout
    bars = _trending_bars()
    strat = MetaLabelBreakout(GOLD)
    p = dict(lookback=20, threshold=0.55)
    model = strat.fit(bars.iloc[:3000], p)
    assert model.clf is not None
    assert check_no_lookahead(bars, strat, p, model=model)
    filtered = (strat.signals(bars, p, model)["signal"] != 0).sum()
    assert 0 <= filtered <= (strat.signals(bars, p)["signal"] != 0).sum()


def test_meta_labels_use_only_fit_window():
    from src.harness.meta_strategy import MetaLabelBreakout
    bars = _trending_bars()
    strat = MetaLabelBreakout(GOLD)
    p = dict(lookback=20, threshold=0.5)
    a = strat.fit(bars.iloc[:3000], p)
    changed = bars.copy()
    changed.iloc[3000:, :4] *= 1.5  # rewrite the future
    b = MetaLabelBreakout(GOLD).fit(changed.iloc[:3000], p)  # fresh instance: no cache
    X = bars.iloc[:3000].assign(volume=1000)
    from src.harness.meta_strategy import FEATURES, signal_features
    feats = signal_features(X, strat._primary(X, p), 20)[FEATURES].dropna().iloc[-200:]
    assert np.allclose(a.clf.predict_proba(feats), b.clf.predict_proba(feats))


def test_anchored_folds_start_at_first_bar():
    idx = pd.date_range("2015-01-01", "2020-01-01", freq="h")
    folds = make_folds(idx, 2.0, 3, pd.Timedelta(hours=24), anchored=True)
    assert all(f.train_start == idx[0] for f in folds)
    assert all(f.train_end < f.test_start for f in folds)


def test_regime_features_are_point_in_time():
    from src.harness.meta_strategy import MetaLabelBreakout
    bars = _trending_bars()
    strat = MetaLabelBreakout(GOLD, regime_features=True)
    p = dict(lookback=20, threshold=0.55)
    model = strat.fit(bars.iloc[:3000], p)
    assert "chop_100" in strat.features
    assert check_no_lookahead(bars, strat, p, model=model)

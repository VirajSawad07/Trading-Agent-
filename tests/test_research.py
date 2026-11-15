import numpy as np
import pandas as pd

from src.harness.costs import load_cost_model
from src.research.intraday_momentum import (N_BARS, gao_last_half_hour, noise_band, shuffle_within_days,
                                            trailing_mean)


def _sessions(n_days=60, seed=0, drift=0.0):
    rng = np.random.default_rng(seed)
    o = np.empty((n_days, N_BARS)); c = np.empty_like(o)
    px = 5000.0
    for d in range(n_days):
        for j in range(N_BARS):
            o[d, j] = px
            px *= 1 + drift + rng.normal(0, 0.002)
            c[d, j] = px
    h, l = np.maximum(o, c) * 1.0005, np.minimum(o, c) * 0.9995
    return {"days": pd.date_range("2024-01-01", periods=n_days, freq="B"), "open": o, "high": h, "low": l,
            "close": c, "volume": np.ones_like(o)}


def test_trailing_mean_uses_only_earlier_days():
    x = np.arange(20, dtype=float)
    m = trailing_mean(x, 3)
    assert np.isnan(m[:3]).all()
    assert m[3] == 1.0 and m[10] == 8.0  # mean of rows 0-2, and of rows 7-9


def test_no_lookahead_truncating_future_days_keeps_past_trades():
    s = _sessions(80)
    cut = {k: (v[:50] if k != "days" else v[:50]) for k, v in s.items()}
    costs = load_cost_model("US500")
    for fn in (noise_band, gao_last_half_hour):
        full = pd.DataFrame(fn(s, "US500", costs))
        part = pd.DataFrame(fn(cut, "US500", costs))
        full = full[full["day"] <= cut["days"][-1]].reset_index(drop=True)
        pd.testing.assert_frame_equal(full, part)


def test_trades_close_inside_the_day_and_costs_are_charged():
    s = _sessions(80, drift=0.001)  # steady trend: the band strategy should trade
    t = pd.DataFrame(noise_band(s, "US500", load_cost_model("US500")))
    assert len(t) > 0
    assert (t["r_net"] < t["r_gross"]).all()
    assert t["bars_held"].between(1, N_BARS - 1).all()


def test_shuffle_keeps_each_days_open_and_bars():
    s = _sessions(30)
    sh = shuffle_within_days(s, seed=1)
    assert np.allclose(sh["open"][:, 0], s["open"][:, 0])
    rel = lambda x: np.sort(x["close"] / x["open"], axis=1)
    assert np.allclose(rel(sh), rel(s))


# ---------------------------------------------------------------- Track 2

def _panel(n=900, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    ret = pd.DataFrame(rng.normal(0.0004, 0.01, (n, 3)), index=idx, columns=["A", "B", "C"])
    ret.iloc[0] = np.nan
    close = (1 + ret.fillna(0)).cumprod() * 100
    return {"close": close, "ret": ret, "trading": close.notna()}


_COSTS = {s: {"point": 0.01, "spread_points": 5.0, "slippage_points": 1.0,
              "financing": {"type": "annual_pct", "long": -2.0, "short": -2.0}} for s in "ABC"}


def test_trend_weights_have_no_lookahead():
    from src.research.trend_following import target_weights
    p = _panel()
    cut = {k: v.iloc[:600] for k, v in p.items()}
    full = target_weights("tsmom_blend", p).iloc[:600]
    part = target_weights("tsmom_blend", cut)
    # The last week of the cut may end early, so compare up to the previous week.
    upto = part.dropna(how="all").index[-2]
    pd.testing.assert_frame_equal(full.loc[:upto], part.loc[:upto])


def test_trend_position_earns_from_the_next_day_and_pays_costs():
    from src.research.trend_following import simulate
    p = _panel()
    sim = simulate("tsmom_12m", p, _COSTS)
    w = sim["weights"]
    expected = (w.shift(1).fillna(0) * p["ret"].fillna(0)).sum(axis=1)
    pd.testing.assert_series_equal(sim["gross"], expected, check_names=False)
    assert (sim["trade_cost"] >= 0).all() and sim["trade_cost"].sum() > 0
    assert sim["financing"].sum() < 0
    assert w.abs().max().max() <= 2.0


# ---------------------------------------------------------------- Track 3

def _daily_bars(n=700, seed=3):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2016-01-01", periods=n)
    c = 1000 * np.cumprod(1 + rng.normal(0.0006, 0.012, n))
    o = c * (1 + rng.normal(0, 0.002, n))
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.004, "low": np.minimum(o, c) * 0.996, "close": c},
                        index=idx)


_IDX_COST = {"point": 0.01, "spread_points": 60.0, "slippage_points": 15.0,
             "financing": {"type": "annual_pct", "long": -2.0, "short": -2.0}}


def test_dip_trades_have_no_lookahead():
    from src.research.index_dips import trades_for
    b = _daily_bars()
    full = pd.DataFrame(trades_for("X", b, _IDX_COST))
    part = pd.DataFrame(trades_for("X", b.iloc[:500], _IDX_COST))
    assert len(part) > 3
    done = full[full["exit_time"] < b.index[499]].reset_index(drop=True)
    pd.testing.assert_frame_equal(done, part[part["exit_time"] < b.index[499]].reset_index(drop=True))


def test_dip_trades_follow_the_rules():
    from src.research.index_dips import indicators, trades_for
    b = _daily_bars()
    t = pd.DataFrame(trades_for("X", b, _IDX_COST))
    x = indicators(b)
    at_entry = x.loc[t["entry_time"]]
    assert (at_entry["close"] > at_entry["sma_trend"]).all() and (at_entry["rsi"] < 10).all()
    assert t["bars_held"].between(1, 10).all()
    assert (t["r_net"] < t["r_gross"]).all()
    stops = t[t["exit_reason"] == "STOP"]
    assert (stops["r_gross"] <= -1 + 1e-9).all()  # a stop loses at least 1 R before costs


# ---------------------------------------------------------------- Step B: the demo bot follows the backtest

def test_dip_trader_decisions_reproduce_backtest_trades():
    """Walk the bars one day at a time as the live bot does (stop at the broker, rules at
    each close) and check it enters and exits on exactly the backtest's bars."""
    from src.live.dip_trader import decide
    from src.research.index_dips import STOP_ATR, indicators, trades_for
    b = _daily_bars(900, seed=5)
    expected = pd.DataFrame(trades_for("X", b, _IDX_COST))[["entry_time", "exit_time"]]
    x_all = indicators(b)
    got, pos, last_exit = [], None, None
    for k in range(len(b)):
        if pos is not None and b["low"].iloc[k] <= pos["stop"]:          # broker stop during bar k
            got.append((pos["entry"], b.index[k])); pos, last_exit = None, k
        x = x_all.iloc[: k + 1]
        held = None if pos is None else k - pos["k"]
        action, _ = decide(x, held)
        if action == "open" and pos is None and last_exit != k and k < len(b) - 1:
            pos = {"entry": b.index[k], "k": k, "stop": x["close"].iloc[-1] - STOP_ATR * x["atr"].iloc[-1]}
        elif action == "close" and pos is not None:
            got.append((pos["entry"], b.index[k])); pos, last_exit = None, k
    got = pd.DataFrame(got, columns=["entry_time", "exit_time"])
    assert len(expected) > 10
    pd.testing.assert_frame_equal(got.iloc[: len(expected)].reset_index(drop=True), expected.reset_index(drop=True))


def test_dip_lot_sizing():
    from src.live.dip_trader import lots_for
    # US500: stop 430 points, $1 per point per lot, $500 risk -> 1.1 lots
    assert lots_for(500, 430, 1.0, 0.1, 0.1, 1000) == 1.1
    # JPN225: min lot 1.0 at $0.63 per point with a 6,700-point stop risks $4,221 -> skip
    assert lots_for(500, 6700, 0.63, 1.0, 1.0, 100) == 0.0
    assert lots_for(500, 377, 1.1, 1.0, 1.0, 100) == 1.0  # FRA40: 1 lot risks $415

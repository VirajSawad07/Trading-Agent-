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

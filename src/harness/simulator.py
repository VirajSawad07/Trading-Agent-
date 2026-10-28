"""Bar-based trade simulator with pessimistic fills, measured in R (multiples of the stop distance).

Rules (all deliberately conservative):
- A signal is decided at the close of bar t and filled at the OPEN of bar t+1.
- MT5 bars are bid prices. Buys fill at ask (bid + spread) and exit at bid; sells the reverse.
- Slippage hurts entries and stop exits. Take-profit is a limit order (no slippage).
- If price gaps through the stop at a bar's open, the fill is the open, not the stop.
- If stop and take-profit are both touched inside one bar, the stop is assumed to hit first.
- One position at a time. An opposite signal closes the trade at the next open and may reverse.
- Swap is charged per night held (triple on the configured weekday, none on weekends).

Results are in R so they are independent of account size. src/harness/account.py turns
R into dollars with lot rounding and minimum-lot constraints.
"""

from datetime import timedelta

import numpy as np
import pandas as pd

from src.harness.costs import CostModel

TRADE_COLUMNS = [
    "signal_time", "entry_time", "exit_time", "direction", "entry_price", "exit_price", "sl_dist",
    "r_gross", "r_net", "exit_reason", "bars_held", "nights",
]


def _swap_nights(entry: pd.Timestamp, exit_: pd.Timestamp, triple_weekday: int) -> int:
    nights = 0
    day = entry.normalize()
    last = exit_.normalize()
    while day < last:
        wd = day.weekday()
        if wd < 5:
            nights += 3 if wd == triple_weekday else 1
        day += timedelta(days=1)
    return nights


def simulate(
    bars: pd.DataFrame,
    signals: pd.DataFrame,
    costs: CostModel,
    max_hold_bars: int = 240,
    exit_on_opposite: bool = True,
    independent: bool = False,
) -> pd.DataFrame:
    """Simulate trades.

    bars: DatetimeIndex, columns open/high/low/close (bid).
    signals: same index, columns signal (1, -1, 0), sl_dist and tp_dist (price distances, > 0).
    independent: grade every signal as its own trade (overlaps allowed, no opposite exits).
    Used to label signals for meta-labeling, not to simulate an account.
    """
    if independent:
        exit_on_opposite = False
    o = bars["open"].to_numpy(float)
    h = bars["high"].to_numpy(float)
    lo = bars["low"].to_numpy(float)
    c = bars["close"].to_numpy(float)
    times = bars.index
    n = len(bars)

    sig = signals["signal"].reindex(bars.index).fillna(0).to_numpy(int)
    sl_d = signals["sl_dist"].reindex(bars.index).to_numpy(float)
    tp_d = signals["tp_dist"].reindex(bars.index).to_numpy(float)
    valid = (sig != 0) & np.isfinite(sl_d) & (sl_d > 0) & np.isfinite(tp_d) & (tp_d > 0)
    valid[-1] = False  # no next bar to fill on
    sig_idx = np.flatnonzero(valid)

    spread, slip, comm = costs.spread, costs.slippage, costs.commission
    rows = []
    p = 0
    while p < len(sig_idx):
        s = sig_idx[p]
        d = int(sig[s])
        j0 = s + 1
        sl_dist, tp_dist = sl_d[s], tp_d[s]

        if d > 0:
            entry = o[j0] + spread + slip
            entry_ref = o[j0]  # bid-based, for gross R
        else:
            entry = o[j0] - slip
            entry_ref = o[j0]
        stop = entry - d * sl_dist
        target = entry + d * tp_dist

        w = min(n - 1, j0 + max_hold_bars - 1)
        hh, ll, oo = h[j0:w + 1], lo[j0:w + 1], o[j0:w + 1]
        if d > 0:
            sl_hit = ll <= stop
            tp_hit = hh >= target
        else:
            sl_hit = hh + spread >= stop
            tp_hit = ll + spread <= target
        any_hit = sl_hit | tp_hit
        e_hit = j0 + int(np.argmax(any_hit)) if any_hit.any() else None

        e_opp = None
        if exit_on_opposite:
            opp = sig[j0:w + 1] == -d
            opp &= valid[j0:w + 1]
            if opp.any():
                k = j0 + int(np.argmax(opp))
                if k + 1 <= n - 1:
                    e_opp = k + 1

        at_open = False
        if e_opp is not None and (e_hit is None or e_opp <= e_hit):
            e = e_opp
            exit_px = (o[e] - slip) if d > 0 else (o[e] + spread + slip)
            reason, at_open = "REVERSE", True
        elif e_hit is not None:
            e = e_hit
            ask_open = o[e] + spread
            if d > 0:
                gap_sl, gap_tp = (e > j0 and o[e] <= stop), (e > j0 and o[e] >= target)
            else:
                gap_sl, gap_tp = (e > j0 and ask_open >= stop), (e > j0 and ask_open <= target)
            if gap_sl:
                exit_px = (o[e] - slip) if d > 0 else (ask_open + slip)
                reason = "SL_GAP"
            elif gap_tp:
                exit_px = o[e] if d > 0 else ask_open
                reason = "TP"
            elif sl_hit[e - j0]:
                exit_px = (stop - slip) if d > 0 else (stop + slip)
                reason = "SL"
            else:
                exit_px = target
                reason = "TP"
        else:
            e = w
            exit_px = c[e] if d > 0 else c[e] + spread
            reason = "END" if w == n - 1 else "TIME"

        exit_ref = exit_px if d > 0 else exit_px - spread  # bid-based
        nights = _swap_nights(times[j0], times[e], costs.triple_swap_weekday)
        pnl_price = d * (exit_px - entry) - comm + nights * costs.swap_per_night(d)
        rows.append((
            times[s], times[j0], times[e], d, entry, exit_px, sl_dist,
            d * (exit_ref - entry_ref) / sl_dist, pnl_price / sl_dist,
            reason, e - j0 + 1, nights,
        ))

        if independent:
            p += 1
            continue
        next_min_sig = e - 1 if at_open else e
        p = int(np.searchsorted(sig_idx, max(next_min_sig, s + 1)))

    return pd.DataFrame(rows, columns=TRADE_COLUMNS)

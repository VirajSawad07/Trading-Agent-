"""Turn R-denominated trades into a dollar equity curve for a real account size.

This is where the minimum lot matters: with $600 on gold, the smallest position can
already risk far more than 1%. Each trade records the risk it actually took.
"""

import math

import numpy as np
import pandas as pd

from src.harness.costs import CostModel


def simulate_account(
    trades: pd.DataFrame,
    costs: CostModel,
    start_equity: float,
    risk_pct: float = 0.01,
    max_risk_pct: float = 0.02,
    max_drawdown_halt: float = 0.10,
) -> dict:
    """Compounding fixed-fractional sizing.

    A trade is taken at min lot when the 1% size rounds below it, but only if the actual
    risk stays within max_risk_pct; otherwise it is skipped. Trading halts once drawdown
    from the equity peak reaches max_drawdown_halt (the kill switch).
    """
    equity = peak = start_equity
    rows = []
    skipped = 0
    halted_at = None
    for t in trades.itertuples(index=False):
        if halted_at is not None:
            break
        loss_per_lot = t.sl_dist * costs.contract_size
        lots = math.floor(equity * risk_pct / loss_per_lot / costs.lot_step + 1e-9) * costs.lot_step
        lots = min(max(lots, costs.min_lot), costs.max_lot)
        actual_risk = lots * loss_per_lot / equity
        if actual_risk > max_risk_pct + 1e-12:
            skipped += 1
            continue
        pnl = t.r_net * t.sl_dist * costs.contract_size * lots
        equity += pnl
        peak = max(peak, equity)
        rows.append((t.exit_time, lots, actual_risk, pnl, equity))
        if equity <= peak * (1 - max_drawdown_halt):
            halted_at = t.exit_time

    curve = pd.DataFrame(rows, columns=["time", "lots", "risk_pct", "pnl", "equity"])
    taken = len(curve)
    if taken:
        eq = np.concatenate([[start_equity], curve["equity"].to_numpy()])
        dd = 1 - eq / np.maximum.accumulate(eq)
        max_dd = float(dd.max())
    else:
        max_dd = 0.0
    return {
        "start_equity": start_equity,
        "final_equity": float(equity),
        "return_pct": float((equity / start_equity - 1) * 100),
        "trades_taken": taken,
        "trades_skipped_min_lot": skipped,
        "median_risk_pct": float(curve["risk_pct"].median() * 100) if taken else 0.0,
        "max_risk_pct": float(curve["risk_pct"].max() * 100) if taken else 0.0,
        "max_drawdown_pct": max_dd * 100,
        "halted_at": str(halted_at) if halted_at is not None else None,
        "curve": curve,
    }

"""Deterministic Risk Engine & Governance Layer.

Principle: AI proposes candidate trades; deterministic risk controls decide whether
those decisions are allowed to execute.
"""

from dataclasses import dataclass
from typing import Optional, Tuple
import yaml


@dataclass
class OrderProposal:
    symbol: str
    action: str            # "BUY" or "SELL"
    entry_price: float
    stop_loss: float
    take_profit: float
    requested_lots: Optional[float] = None
    strategy_id: str = "default"


@dataclass
class AccountState:
    balance: float
    equity: float
    open_positions: int
    daily_starting_equity: float
    is_demo: bool = True


@dataclass
class MarketConditions:
    current_spread_points: float
    bid: float
    ask: float


class RiskEngine:
    def __init__(self, config_path: str = "config/risk_limits.yaml"):
        with open(config_path, "r") as f:
            cfg = yaml.safe_load(f)
        
        limits = cfg.get("risk_limits", {})
        self.max_risk_per_trade_pct = limits.get("max_risk_per_trade_pct", 0.01)
        self.max_daily_loss_pct = limits.get("max_daily_loss_pct", 0.03)
        self.max_total_drawdown_pct = limits.get("max_total_drawdown_pct", 0.10)
        self.max_open_positions = limits.get("max_open_positions", 1)
        self.max_spread_points = limits.get("max_spread_points", 50)
        self.min_lot_size = limits.get("min_lot_size", 0.01)
        self.max_lot_size = limits.get("max_lot_size", 2.0)
        self.lot_step = limits.get("lot_step", 0.01)
        self.demo_account_only = limits.get("demo_account_only", True)
        self.enforce_stop_loss = limits.get("enforce_stop_loss", True)
        self.kill_switch_active = False

    def trigger_kill_switch(self, reason: str):
        """Halts all further trade execution."""
        self.kill_switch_active = True
        return f"KILL SWITCH TRIGGERED: {reason}"

    def reset_kill_switch(self):
        """Manually or session-reset the kill switch."""
        self.kill_switch_active = False

    def calculate_lot_size(
        self,
        equity: float,
        entry_price: float,
        stop_loss_price: float,
        contract_size: float = 100.0,
    ) -> float:
        """Calculates position size in lots based on fixed fractional equity risk.
        
        Risk Amount ($) = Equity * max_risk_per_trade_pct
        Distance per unit ($) = abs(entry_price - stop_loss_price)
        Loss per 1.0 Lot ($) = Distance * contract_size
        Lots = Risk Amount / Loss per 1.0 Lot
        """
        risk_capital = equity * self.max_risk_per_trade_pct
        stop_distance = abs(entry_price - stop_loss_price)

        if stop_distance <= 0:
            return 0.0

        loss_per_lot = stop_distance * contract_size
        if loss_per_lot <= 0:
            return 0.0

        raw_lots = risk_capital / loss_per_lot

        # Round down to nearest lot step
        stepped_lots = int(raw_lots / self.lot_step) * self.lot_step
        stepped_lots = round(stepped_lots, 2)

        # Clamp between min and max allowed
        if stepped_lots < self.min_lot_size:
            # On small/micro accounts (e.g. <= $500), allow minimum 0.01 lots so small accounts can trade
            if equity <= 500.0 and self.min_lot_size <= 0.01:
                return 0.01
            return 0.0
        return min(stepped_lots, self.max_lot_size)

    def validate_proposal(
        self,
        proposal: OrderProposal,
        account: AccountState,
        market: MarketConditions,
        contract_size: float = 100.0,
    ) -> Tuple[bool, str, Optional[float]]:
        """Audits an AI trade proposal against all safety boundaries.
        
        Returns:
            (approved: bool, rejection_reason: str, approved_lots: Optional[float])
        """
        # 1. Kill switch check
        if self.kill_switch_active:
            return False, "Execution rejected: Kill switch is active.", None

        # 2. Live account protection check
        if self.demo_account_only and not account.is_demo:
            self.trigger_kill_switch("Attempted to trade on a LIVE account when demo_account_only is True.")
            return False, "SAFETY VIOLATION: Live account trade blocked.", None

        # 3. Open positions limit
        if account.open_positions >= self.max_open_positions:
            return False, f"Max open positions reached ({account.open_positions}/{self.max_open_positions}).", None

        # 4. Daily Drawdown Circuit Breaker
        daily_loss_pct = (account.daily_starting_equity - account.equity) / max(account.daily_starting_equity, 1.0)
        if daily_loss_pct >= self.max_daily_loss_pct:
            self.trigger_kill_switch(f"Daily drawdown limit breached ({daily_loss_pct:.2%} >= {self.max_daily_loss_pct:.2%}).")
            return False, f"Daily drawdown limit reached ({daily_loss_pct:.2%}).", None

        # 5. Spread Check (Protection against news volatility / slippage)
        if market.current_spread_points > self.max_spread_points:
            return False, f"Spread too high ({market.current_spread_points:.1f} pts > {self.max_spread_points} pts limit).", None

        # 6. Stop-loss validation
        if self.enforce_stop_loss:
            if proposal.stop_loss <= 0:
                return False, "Stop loss is required but not provided.", None

            if proposal.action == "BUY" and proposal.stop_loss >= proposal.entry_price:
                return False, f"Invalid BUY stop loss ({proposal.stop_loss} >= {proposal.entry_price}).", None

            if proposal.action == "SELL" and proposal.stop_loss <= proposal.entry_price:
                return False, f"Invalid SELL stop loss ({proposal.stop_loss} <= {proposal.entry_price}).", None

        # 7. Dynamic Position Sizing
        approved_lots = self.calculate_lot_size(
            equity=account.equity,
            entry_price=proposal.entry_price,
            stop_loss_price=proposal.stop_loss,
            contract_size=contract_size,
        )

        if approved_lots < self.min_lot_size:
            return False, f"Calculated position size ({approved_lots} lots) below broker minimum ({self.min_lot_size}).", None

        return True, "Approved", approved_lots

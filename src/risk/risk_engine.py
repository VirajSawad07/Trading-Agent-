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
    peak_equity: Optional[float] = None  # highest equity seen; enables the total-drawdown breaker


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
        # The broker minimum lot may risk more than 1%; allow it only up to this cap.
        self.max_min_lot_risk_pct = limits.get("max_min_lot_risk_pct", 2 * self.max_risk_per_trade_pct)
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
            # Small accounts: the minimum lot is allowed only if its risk stays under the cap.
            min_lot_risk = self.min_lot_size * loss_per_lot / max(equity, 1e-9)
            return self.min_lot_size if min_lot_risk <= self.max_min_lot_risk_pct else 0.0
        return min(stepped_lots, self.max_lot_size)

    def validate_proposal(
        self,
        proposal: OrderProposal,
        account: AccountState,
        market: MarketConditions,
        contract_size: float = 100.0,
        sizing_equity: Optional[float] = None,
    ) -> Tuple[bool, str, Optional[float]]:
        """Audits an AI trade proposal against all safety boundaries.

        sizing_equity: size the trade as if the account held this much (e.g. the planned
        real-money balance). Breakers still use the account state passed in.
        
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

        # 4b. Total drawdown from the equity peak
        if account.peak_equity:
            dd = (account.peak_equity - account.equity) / max(account.peak_equity, 1.0)
            if dd >= self.max_total_drawdown_pct:
                self.trigger_kill_switch(f"Total drawdown limit breached ({dd:.2%} >= {self.max_total_drawdown_pct:.2%}).")
                return False, f"Total drawdown limit reached ({dd:.2%} from peak).", None

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
            equity=sizing_equity if sizing_equity else account.equity,
            entry_price=proposal.entry_price,
            stop_loss_price=proposal.stop_loss,
            contract_size=contract_size,
        )

        if approved_lots < self.min_lot_size:
            return False, (f"Even the minimum lot ({self.min_lot_size}) would risk more than "
                           f"{self.max_min_lot_risk_pct:.0%} of equity with this stop."), None

        return True, "Approved", approved_lots

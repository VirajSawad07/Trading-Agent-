"""MT5 Demo Execution Gateway with Strict Safety Interlocks."""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional
import yaml
from src.risk.risk_engine import AccountState, MarketConditions, OrderProposal

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False


@dataclass
class ExecutionResult:
    success: bool
    ticket: Optional[int]
    action: str
    symbol: str
    lots: float
    price: float
    sl: float
    tp: float
    timestamp: str
    message: str


class DemoGateway:
    """Gateway that communicates with MetaTrader 5 terminal exclusively for DEMO accounts."""

    def __init__(self, risk_config_path: str = "config/risk_limits.yaml", magic_number: int = 888999):
        with open(risk_config_path, "r") as f:
            cfg = yaml.safe_load(f)
        self.demo_account_only = cfg.get("risk_limits", {}).get("demo_account_only", True)
        self.magic_number = magic_number

    def verify_demo_account(self) -> Dict:
        """Asserts that the terminal is logged into a valid DEMO account."""
        if not MT5_AVAILABLE:
            raise RuntimeError("MetaTrader5 python library is not installed.")

        acc = mt5.account_info()
        if acc is None:
            err = mt5.last_error()
            raise ConnectionError(f"Failed to query MT5 account information: {err}. Ensure MT5 terminal is open.")

        is_demo = acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO

        if self.demo_account_only and not is_demo:
            raise PermissionError(
                f"SECURITY VIOLATION: MT5 account #{acc.login} is a LIVE/CONTEST account (trade_mode={acc.trade_mode}). "
                "Execution is strictly locked to DEMO accounts only by policy."
            )

        return {
            "login": acc.login,
            "name": acc.name,
            "server": acc.server,
            "balance": acc.balance,
            "equity": acc.equity,
            "currency": acc.currency,
            "is_demo": is_demo,
        }

    def get_account_state(self, daily_starting_equity: Optional[float] = None) -> AccountState:
        acc = mt5.account_info()
        if acc is None:
            mt5.initialize()
            acc = mt5.account_info()
        if acc is None:
            raise ConnectionError("MT5 account info unavailable.")

        positions = mt5.positions_get()
        num_positions = len(positions) if positions is not None else 0
        starting_equity = daily_starting_equity or acc.equity

        return AccountState(
            balance=acc.balance,
            equity=acc.equity,
            open_positions=num_positions,
            daily_starting_equity=starting_equity,
            is_demo=(acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO),
        )

    def get_market_conditions(self, symbol: str = "XAUUSD") -> MarketConditions:
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise RuntimeError(f"Unable to get market tick for {symbol}. Ensure symbol is visible in Market Watch.")

        sym_info = mt5.symbol_info(symbol)
        point = sym_info.point if sym_info else 0.01

        spread_points = (tick.ask - tick.bid) / point

        return MarketConditions(
            current_spread_points=round(spread_points, 1),
            bid=tick.bid,
            ask=tick.ask,
        )

    def send_order(self, proposal: OrderProposal, lots: float) -> ExecutionResult:
        """Dispatches an order to the MT5 terminal with SL and TP attached."""
        self.verify_demo_account()

        is_buy = proposal.action == "BUY"
        tick = mt5.symbol_info_tick(proposal.symbol)
        if tick is None:
            return ExecutionResult(
                success=False,
                ticket=None,
                action=proposal.action,
                symbol=proposal.symbol,
                lots=lots,
                price=0.0,
                sl=proposal.stop_loss,
                tp=proposal.take_profit,
                timestamp=datetime.now().isoformat(),
                message=f"Failed to get live tick for {proposal.symbol}",
            )

        fill_price = tick.ask if is_buy else tick.bid
        order_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL

        # Try IOC first, with fallback to RETURN
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": proposal.symbol,
            "volume": float(lots),
            "type": order_type,
            "price": float(fill_price),
            "sl": float(proposal.stop_loss),
            "tp": float(proposal.take_profit),
            "deviation": 20,
            "magic": self.magic_number,
            "comment": "AI_Gold_MultiAgent",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            # Fallback to ORDER_FILLING_RETURN if broker doesn't support IOC
            request["type_filling"] = mt5.ORDER_FILLING_RETURN
            result = mt5.order_send(request)

        if result is None:
            err = mt5.last_error()
            return ExecutionResult(
                success=False,
                ticket=None,
                action=proposal.action,
                symbol=proposal.symbol,
                lots=lots,
                price=fill_price,
                sl=proposal.stop_loss,
                tp=proposal.take_profit,
                timestamp=datetime.now().isoformat(),
                message=f"order_send failed: {err}",
            )

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return ExecutionResult(
                success=False,
                ticket=None,
                action=proposal.action,
                symbol=proposal.symbol,
                lots=lots,
                price=fill_price,
                sl=proposal.stop_loss,
                tp=proposal.take_profit,
                timestamp=datetime.now().isoformat(),
                message=f"Order rejected by broker (retcode={result.retcode}: {result.comment})",
            )

        return ExecutionResult(
            success=True,
            ticket=result.order,
            action=proposal.action,
            symbol=proposal.symbol,
            lots=lots,
            price=result.price,
            sl=proposal.stop_loss,
            tp=proposal.take_profit,
            timestamp=datetime.now().isoformat(),
            message=f"Order executed successfully: #{result.order}",
        )

    def close_all_positions(self, symbol: Optional[str] = None) -> List[Dict]:
        """Emergency liquidator: Closes all open positions matching symbol or magic number."""
        self.verify_demo_account()
        positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
        if not positions:
            return []

        results = []
        for pos in positions:
            tick = mt5.symbol_info_tick(pos.symbol)
            if not tick:
                continue

            close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
            price = tick.bid if pos.type == mt5.POSITION_TYPE_BUY else tick.ask

            close_request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "position": pos.ticket,
                "symbol": pos.symbol,
                "volume": pos.volume,
                "type": close_type,
                "price": price,
                "deviation": 20,
                "magic": self.magic_number,
                "comment": "KillSwitch_Close",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            res = mt5.order_send(close_request)
            if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
                close_request["type_filling"] = mt5.ORDER_FILLING_RETURN
                res = mt5.order_send(close_request)

            results.append({"ticket": pos.ticket, "symbol": pos.symbol, "success": res is not None and res.retcode == mt5.TRADE_RETCODE_DONE})

        return results

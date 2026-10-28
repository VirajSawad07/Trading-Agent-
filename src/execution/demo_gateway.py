"""MT5 Demo Execution Gateway with Strict Safety Interlocks.

Every position this bot opens carries its magic number, and every query/close here is
filtered by it, so the bot never sees or touches trades it did not open.

Orders are idempotent: each carries a client tag (in the comment) and, before any retry,
the gateway checks whether a position with that tag already exists. Only retcodes that
mean "nothing was filled" (requote / price moved) are retried, so a slow or ambiguous
reply can never turn into a double fill.
"""

import time
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

# Broker replies that guarantee no fill happened, so a retry is safe.
RETRYABLE = {10004, 10020, 10021}  # REQUOTE, PRICE_CHANGED, PRICE_OFF


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

    def bot_positions(self, symbol: Optional[str] = None) -> list:
        """Open positions opened by this bot (matching magic number)."""
        positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
        return [p for p in (positions or []) if p.magic == self.magic_number]

    def get_account_state(self, daily_starting_equity: Optional[float] = None,
                          peak_equity: Optional[float] = None) -> AccountState:
        acc = mt5.account_info()
        if acc is None:
            raise ConnectionError("MT5 account info unavailable.")

        return AccountState(
            balance=acc.balance,
            equity=acc.equity,
            open_positions=len(self.bot_positions()),
            daily_starting_equity=daily_starting_equity or acc.equity,
            is_demo=(acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO),
            peak_equity=peak_equity,
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

    def _filling_mode(self, symbol: str) -> int:
        """Pick a filling mode the symbol actually supports instead of trial and error."""
        info = mt5.symbol_info(symbol)
        flags = info.filling_mode if info else 0
        if flags & 1:
            return mt5.ORDER_FILLING_FOK
        if flags & 2:
            return mt5.ORDER_FILLING_IOC
        return mt5.ORDER_FILLING_RETURN

    def _find_tagged(self, symbol: str, tag: str):
        return next((p for p in self.bot_positions(symbol) if p.comment == tag), None)

    def _result(self, proposal, lots, price, message, success=False, ticket=None) -> ExecutionResult:
        return ExecutionResult(
            success=success, ticket=ticket, action=proposal.action, symbol=proposal.symbol, lots=lots,
            price=price, sl=proposal.stop_loss, tp=proposal.take_profit,
            timestamp=datetime.now().isoformat(), message=message,
        )

    def send_order(self, proposal: OrderProposal, lots: float, client_tag: Optional[str] = None,
                   max_retries: int = 3) -> ExecutionResult:
        """Dispatches an order to the MT5 terminal with SL and TP attached.

        client_tag: unique id for this decision (max 31 chars). If a position with this tag
        already exists, nothing is sent and that position is reported instead.
        """
        self.verify_demo_account()
        tag = (client_tag or "AI_Gold_MultiAgent")[:31]

        if client_tag:
            existing = self._find_tagged(proposal.symbol, tag)
            if existing:
                return self._result(proposal, existing.volume, existing.price_open,
                                    f"Already filled earlier as #{existing.ticket}; not resent.", True, existing.ticket)

        is_buy = proposal.action == "BUY"
        filling = self._filling_mode(proposal.symbol)
        last_msg = "not sent"
        for attempt in range(max_retries):
            tick = mt5.symbol_info_tick(proposal.symbol)
            if tick is None:
                return self._result(proposal, lots, 0.0, f"Failed to get live tick for {proposal.symbol}")
            fill_price = tick.ask if is_buy else tick.bid
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": proposal.symbol,
                "volume": float(lots),
                "type": mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL,
                "price": float(fill_price),
                "sl": float(proposal.stop_loss),
                "tp": float(proposal.take_profit),
                "deviation": 20,
                "magic": self.magic_number,
                "comment": tag,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": filling,
            }
            result = mt5.order_send(request)

            if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
                return self._result(proposal, lots, result.price, f"Order executed successfully: #{result.order}",
                                    True, result.order)

            # Ambiguous outcome (no reply, timeout, anything not known-safe): look before retrying.
            time.sleep(0.5)
            existing = self._find_tagged(proposal.symbol, tag) if client_tag else None
            if existing:
                return self._result(proposal, existing.volume, existing.price_open,
                                    f"Filled despite reply {getattr(result, 'retcode', None)}: #{existing.ticket}",
                                    True, existing.ticket)
            if result is None:
                last_msg = f"order_send failed: {mt5.last_error()}"
                break
            last_msg = f"Order rejected by broker (retcode={result.retcode}: {result.comment})"
            if result.retcode not in RETRYABLE:
                break

        return self._result(proposal, lots, 0.0, last_msg)

    def modify_sltp(self, ticket: int, symbol: str, sl: float, tp: float) -> bool:
        """Move a bot position's stop/target (used to re-anchor them to the actual fill price)."""
        res = mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": ticket, "symbol": symbol,
                              "sl": float(sl), "tp": float(tp), "magic": self.magic_number})
        return res is not None and res.retcode == mt5.TRADE_RETCODE_DONE

    def close_position(self, pos, comment: str = "Bot_Close") -> bool:
        tick = mt5.symbol_info_tick(pos.symbol)
        if not tick:
            return False
        is_buy = pos.type == mt5.POSITION_TYPE_BUY
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": pos.ticket,
            "symbol": pos.symbol,
            "volume": pos.volume,
            "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
            "price": tick.bid if is_buy else tick.ask,
            "deviation": 20,
            "magic": self.magic_number,
            "comment": comment[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._filling_mode(pos.symbol),
        }
        res = mt5.order_send(request)
        if res is not None and res.retcode == mt5.TRADE_RETCODE_DONE:
            return True
        # Closing by position ticket is naturally idempotent: retry only if it is still open.
        time.sleep(0.5)
        if not any(p.ticket == pos.ticket for p in self.bot_positions(pos.symbol)):
            return True
        if res is not None and res.retcode in RETRYABLE:
            res = mt5.order_send({**request, "price": (mt5.symbol_info_tick(pos.symbol).bid if is_buy
                                                       else mt5.symbol_info_tick(pos.symbol).ask)})
            return res is not None and res.retcode == mt5.TRADE_RETCODE_DONE
        return False

    def close_all_positions(self, symbol: Optional[str] = None) -> List[Dict]:
        """Emergency liquidator: closes every position this bot opened (magic number match)."""
        self.verify_demo_account()
        return [{"ticket": p.ticket, "symbol": p.symbol, "success": self.close_position(p, "KillSwitch_Close")}
                for p in self.bot_positions(symbol)]

    def position_deals(self, position_id: int) -> list:
        """All deals (entry and exit) of one position, including broker-side SL/TP exits."""
        return list(mt5.history_deals_get(position=position_id) or [])

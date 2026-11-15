"""Signals-only mode: run a bot's decisions on a real account's prices without any orders.

The bots trade only on demo. When MT5 is logged in to a real account they can instead run
in signals-only mode: every decision (buy, sell, hold, skip) is logged to its own ledger,
but the gateway's order functions are replaced by ones that raise, so no order can be
sent, changed or closed. Placing real trades stays with the account owner.

If the terminal switches back to a demo account, a signals-only bot exits with
SIGNALS_DEMO_EXIT so the start scripts can restart it in normal (demo trading) mode.
"""

from pathlib import Path

import yaml

SIGNALS_DEMO_EXIT = 4


class SwitchToTrading(Exception):
    """The terminal is on a demo account again: leave signals-only mode."""


def broker_symbol(symbol: str, server: str, path: str = "config/broker_symbols.yaml") -> str:
    p = Path(path)
    table = (yaml.safe_load(p.read_text()) or {}) if p.exists() else {}
    return (table.get(server) or {}).get(symbol, symbol)


def forbid_orders(gateway):
    """Make every order path of a DemoGateway raise. Used in signals-only mode."""
    def refuse(*_, **__):
        raise RuntimeError("Signals-only mode: orders are disabled.")
    for name in ("send_order", "close_position", "close_all_positions", "modify_sltp"):
        setattr(gateway, name, refuse)
    return gateway


def usd_per_account_unit(mt5) -> float:
    """USD value of one unit of the account currency (e.g. 1 GBP), from the terminal's own quotes."""
    cur = mt5.account_info().currency
    if cur == "USD":
        return 1.0
    for name in (f"{cur}USD", f"{cur}USDs"):
        mt5.symbol_select(name, True)
        t = mt5.symbol_info_tick(name)
        if t is not None and t.bid > 0:
            return t.bid
    for name in (f"USD{cur}", f"USD{cur}s"):
        mt5.symbol_select(name, True)
        t = mt5.symbol_info_tick(name)
        if t is not None and t.ask > 0:
            return 1.0 / t.ask
    raise RuntimeError(f"No quote to convert {cur} to USD")


def real_equity_usd(mt5) -> float:
    return mt5.account_info().equity * usd_per_account_unit(mt5)

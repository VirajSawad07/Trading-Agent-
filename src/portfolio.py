"""Portfolio Dashboard CLI — Displays live balance, floating PnL, and trade performance."""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from src.data.mt5_connector import MT5Connector

try:
    import MetaTrader5 as mt5
except ImportError:
    pass


def main():
    console = Console()
    connector = MT5Connector()
    if not connector.connect():
        console.print("[red]MT5 is not open. Please launch MetaTrader 5.[/red]")
        return

    try:
        acc = mt5.account_info()
        positions = mt5.positions_get()
        from datetime import datetime, timedelta
        deals = mt5.history_deals_get(datetime.now() - timedelta(days=30), datetime.now())

        # 1. Account Summary Panel
        floating_pnl = acc.profit
        pnl_color = "green" if floating_pnl >= 0 else "red"
        pnl_sign = "+" if floating_pnl > 0 else ""

        summary_table = Table(title="[bold gold1]Account Financial Status[/bold gold1]")
        summary_table.add_column("Item", style="cyan")
        summary_table.add_column("Value", style="bold white")

        summary_table.add_row("Account Login", f"#{acc.login} ({acc.name})")
        summary_table.add_row("Account Mode", "DEMO (Safe)" if acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO else "LIVE")
        summary_table.add_row("Account Balance", f"${acc.balance:,.2f} {acc.currency}")
        summary_table.add_row("Current Equity", f"${acc.equity:,.2f} {acc.currency}")
        summary_table.add_row("Live Floating PnL", f"[{pnl_color}]{pnl_sign}${floating_pnl:,.2f} {acc.currency}[/{pnl_color}]")
        summary_table.add_row("Free Margin", f"${acc.margin_free:,.2f} {acc.currency}")
        console.print(summary_table)

        # 2. Active Open Positions Table
        if positions and len(positions) > 0:
            pos_table = Table(title="[bold cyan]Live Open Positions[/bold cyan]")
            pos_table.add_column("Ticket", style="dim")
            pos_table.add_column("Symbol", style="bold yellow")
            pos_table.add_column("Type", style="cyan")
            pos_table.add_column("Lots", style="white")
            pos_table.add_column("Open Price", style="white")
            pos_table.add_column("Current Price", style="white")
            pos_table.add_column("Stop Loss", style="red")
            pos_table.add_column("Take Profit", style="green")
            pos_table.add_column("Live Profit", style="bold")

            for p in positions:
                action_str = "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL"
                p_color = "green" if p.profit >= 0 else "red"
                sign = "+" if p.profit > 0 else ""
                pos_table.add_row(
                    str(p.ticket),
                    p.symbol,
                    action_str,
                    f"{p.volume:.2f}",
                    f"${p.price_open:.2f}",
                    f"${p.price_current:.2f}",
                    f"${p.sl:.2f}",
                    f"${p.tp:.2f}",
                    f"[{p_color}]{sign}${p.profit:.2f}[/{p_color}]",
                )
            console.print(pos_table)
        else:
            console.print("[dim]No active open positions currently.[/dim]")

        # 3. Overall Performance Status
        if acc.equity > acc.balance:
            profit_dollars = acc.equity - acc.balance
            pct = (profit_dollars / acc.balance) * 100.0
            console.print(f"\n[bold green]STATUS: YOU ARE IN PROFIT! (+${profit_dollars:,.2f} / +{pct:.3f}% overall)[/bold green]")
        elif acc.equity < acc.balance:
            loss_dollars = acc.balance - acc.equity
            pct = (loss_dollars / acc.balance) * 100.0
            console.print(f"\n[bold red]STATUS: IN DRAWDOWN (-${loss_dollars:,.2f} / -{pct:.3f}% overall)[/bold red]")
        else:
            console.print("\n[bold cyan]STATUS: BREAK-EVEN ($0.00 PnL)[/bold cyan]")

    finally:
        connector.disconnect()


if __name__ == "__main__":
    main()

"""Test Trade Script — Places an immediate 0.01 lot verification trade on MT5 Demo."""

import time
from rich.console import Console
from rich.panel import Panel
from src.data.mt5_connector import MT5Connector
from src.execution.demo_gateway import DemoGateway
from src.risk.risk_engine import OrderProposal

try:
    import MetaTrader5 as mt5
except ImportError:
    pass


def main():
    console = Console()
    console.print(Panel.fit("[bold cyan]MT5 Live Demo Trade Verification[/bold cyan]"))

    connector = MT5Connector()
    if not connector.connect():
        console.print("[red]Could not connect to MT5 terminal.[/red]")
        return

    term = mt5.terminal_info()
    if not term.trade_allowed:
        console.print("[bold red][CANNOT TRADE YET]: 'Algo Trading' is DISABLED in MetaTrader 5![/bold red]")
        console.print("\n[bold yellow]To fix this in 5 seconds:[/bold yellow]")
        console.print("1. Look at the top toolbar in your MetaTrader 5 window.")
        console.print("2. Click the [bold green]'Algo Trading'[/bold green] button so it turns GREEN (play icon).")
        console.print("3. Or press [bold cyan]Ctrl + E[/bold cyan] (shortcut to toggle Algo Trading).")
        console.print("4. Then run this script again!")
        connector.disconnect()
        return

    gateway = DemoGateway()
    try:
        acc = gateway.verify_demo_account()
        console.print(f"[green]Verified Demo Account #{acc['login']} ({acc['name']})[/green]")
        
        market = gateway.get_market_conditions("XAUUSD")
        console.print(f"Current Gold Price: Bid=${market.bid:.2f} | Ask=${market.ask:.2f} | Spread={market.current_spread_points:.1f} pts")

        # Create a test BUY order proposal with 0.01 lot and tight SL/TP
        sl_price = round(market.bid - 5.0, 2)
        tp_price = round(market.ask + 5.0, 2)

        proposal = OrderProposal(
            symbol="XAUUSD",
            action="BUY",
            entry_price=market.ask,
            stop_loss=sl_price,
            take_profit=tp_price,
            strategy_id="Verification_Test",
        )

        console.print(f"[bold cyan]Sending test BUY order: 0.01 lots @ ${market.ask:.2f} (SL: ${sl_price}, TP: ${tp_price})...[/bold cyan]")
        result = gateway.send_order(proposal, lots=0.01)

        if result.success:
            console.print(f"[bold green]SUCCESS! Trade executed on MT5 Demo![/bold green]")
            console.print(f"Ticket: [bold yellow]#{result.ticket}[/bold yellow] | Price: ${result.price:.2f}")
            console.print("\n[bold green]Look at your MT5 terminal:[/bold green]")
            console.print("1. Click the [bold cyan]'Trade'[/bold cyan] tab at the bottom left of your Toolbox.")
            console.print(f"2. You will now see your live open position: [bold yellow]XAUUSD BUY 0.01[/bold yellow]!")
        else:
            console.print(f"[bold red]Order failed:[/bold red] {result.message}")

    except Exception as e:
        console.print(f"[bold red]Error: {e}[/bold red]")
    finally:
        connector.disconnect()


if __name__ == "__main__":
    main()

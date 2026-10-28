"""Emergency Kill Switch Module & CLI Script.

Instantly liquidates all open positions and cancels pending orders on MT5.
"""

import os
from typing import Dict, List
import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False

from src.data.mt5_connector import MT5Connector
from src.execution.demo_gateway import DemoGateway


def emergency_liquidate_all() -> List[Dict]:
    """Programmatic entry point to liquidate all open positions."""
    load_dotenv()
    if not MT5_AVAILABLE or not mt5.initialize():
        return []
    try:
        gateway = DemoGateway()
        return gateway.close_all_positions(symbol=None)
    except Exception as e:
        print(f"[KillSwitch] Error during emergency liquidation: {e}")
        return []


def main():
    console = Console()
    console.print("[bold red]================ EMERGENCY KILL SWITCH ================[/bold red]")
    
    load_dotenv()
    with open("config/config.yaml", "r") as f:
        cfg = yaml.safe_load(f)

    symbol = cfg.get("symbol", "XAUUSD")
    connector = MT5Connector()

    if not connector.connect():
        console.print("[red]Failed to connect to MetaTrader 5 terminal. Is MT5 open?[/red]")
        return

    try:
        gateway = DemoGateway()
        account_info = gateway.verify_demo_account()
        console.print(f"[bold yellow]Connected Account:[/bold yellow] #{account_info['login']} ({account_info['name']}) on {account_info['server']}")
        console.print("[bold red]Liquidating all open positions...[/bold red]")

        results = gateway.close_all_positions(symbol=None)
        
        table = Table(title="[bold red]Liquidated Positions Report[/bold red]")
        table.add_column("Ticket", style="cyan")
        table.add_column("Symbol", style="yellow")
        table.add_column("Status", style="bold green")

        if not results:
            console.print("[green]No open positions found. Account is flat.[/green]")
        else:
            for r in results:
                status_str = "[green]CLOSED[/green]" if r["success"] else "[red]FAILED[/red]"
                table.add_row(str(r["ticket"]), r["symbol"], status_str)
            console.print(table)

    except Exception as e:
        console.print(f"[bold red]Kill switch error: {e}[/bold red]")
    finally:
        connector.disconnect()
        console.print("[bold cyan]Kill switch completed.[/bold cyan]")


if __name__ == "__main__":
    main()

"""Live MT5 Demo Trading Engine & Candle Polling Loop."""

import argparse
import logging
import os
import sys
import time
from datetime import datetime
from typing import List, Optional

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from src.data.mt5_connector import MT5Connector
from src.execution.demo_gateway import DemoGateway
from src.orchestration.coordinator import DecisionCoordinator
from src.risk.risk_engine import RiskEngine


def run_live_trader(
    symbols: Optional[List[str]] = None,
    symbol: str = "XAUUSD",
    timeframe: str = "H1",
    poll_interval: int = 5,
    capital: Optional[float] = None,
    fixed_lots: Optional[float] = None,
):
    """capital: size trades as if the account held this much (risk checks still use real equity).
    fixed_lots: an upper cap on the risk engine's lot size, never a bypass of it."""
    if not symbols:
        symbols = [symbol]

    console = Console()
    mode_desc = (f"Sizing as ${capital:,.0f}" if capital else "Sizing on real equity") + (f" • lot cap {fixed_lots}" if fixed_lots else "")
    console.print(Panel.fit(
        f"[bold gold1]MT5 AI Quantitative Trading Desk — Live Execution Engine[/bold gold1]\n"
        f"[cyan]Universe: {', '.join(symbols)} | Timeframe: {timeframe} | Poll: {poll_interval}s\n"
        f"Mode: [bold yellow]{mode_desc}[/bold yellow][/cyan]"
    ))

    load_dotenv()
    with open("config/config.yaml", "r") as f:
        config = yaml.safe_load(f)

    # 1. MT5 Terminal Connection
    connector = MT5Connector()
    if not connector.connect():
        console.print("[bold red]Connection failed:[/bold red] MT5 desktop terminal is not open. Please launch MetaTrader 5 and log in to your Demo account.")
        return

    gateway = DemoGateway()
    try:
        # 2. Strict Demo Account Verification
        account_info = gateway.verify_demo_account()
        console.print(f"[bold green]Verified Demo Account:[/bold green] #{account_info['login']} ({account_info['name']}) | Broker Balance: ${account_info['balance']:,.2f} | Broker Equity: ${account_info['equity']:,.2f}")
        if capital:
            console.print(f"[bold cyan]Sizing Profile:[/bold cyan] trades sized as if the account held [bold yellow]${capital:,.2f}[/bold yellow]; breakers use real equity.")
    except Exception as e:
        console.print(f"[bold red]Safety Check Failed:[/bold red] {e}")
        connector.disconnect()
        return

    # 3. System Initialization
    from src.agents.quant_agent import QuantAgent
    quant_agent = QuantAgent(
        timeframe=timeframe,
        atr_multiplier_sl=1.5,
        atr_multiplier_tp=4.5,  # Strict 1:3 Risk to Reward Ratio
    )
    coordinator = DecisionCoordinator(quant_agent=quant_agent, allow_technical_fallback=True)
    risk_engine = RiskEngine()

    daily_starting_equity = account_info["equity"]
    peak_equity = account_info["equity"]
    current_day = datetime.now().date()
    last_processed_candle_times = {sym: None for sym in symbols}

    console.print(f"[bold green]Agent Ready![/bold green] Actively scanning [bold yellow]{', '.join(symbols)} ({timeframe})[/bold yellow] candles. Press [bold red]Ctrl+C[/bold red] to stop.\n")

    try:
        while True:
            try:
                account_state = gateway.get_account_state(daily_starting_equity=daily_starting_equity,
                                                          peak_equity=peak_equity)
                if datetime.now().date() != current_day:  # new day: reset the daily-loss baseline
                    current_day = datetime.now().date()
                    daily_starting_equity = account_state.equity
                    account_state.daily_starting_equity = daily_starting_equity
                peak_equity = max(peak_equity, account_state.equity)
            except Exception as acc_err:
                console.print(f"[yellow]MT5 connection retry:[/yellow] {acc_err}. Attempting reconnection...")
                connector.connect()
                time.sleep(poll_interval)
                continue

            for sym in symbols:
                try:
                    market = gateway.get_market_conditions(symbol=sym)
                    bars_df = connector.fetch_historical_bars(symbol=sym, timeframe_str=timeframe, bars_count=100)
                    latest_candle_time = bars_df.index[-1]

                    if last_processed_candle_times[sym] is None:
                        last_processed_candle_times[sym] = latest_candle_time
                        console.print(f"[{datetime.now().strftime('%H:%M:%S')}] [{sym}] Initialized with bar {latest_candle_time} (Current Bid: ${market.bid:.2f}).")
                        continue

                    if latest_candle_time != last_processed_candle_times[sym]:
                        last_processed_candle_times[sym] = latest_candle_time
                        completed_bars = bars_df.iloc[:-1]

                        console.print(f"\n[bold cyan]====== [{sym}] New Candle Closed ({latest_candle_time}) ======[/bold cyan]")
                        console.print(f"Bid: ${market.bid:.2f} | Ask: ${market.ask:.2f} | Spread: {market.current_spread_points:.1f} pts | Open Positions: {account_state.open_positions}")

                        # Multi-Agent Arbitration
                        decision = coordinator.arbitrate(
                            df_history=completed_bars,
                            symbol=sym,
                            spread_points=market.current_spread_points,
                        )

                        # Deliberation Panel
                        audit_table = Table(title=f"[bold yellow]{sym} Deliberation Audit[/bold yellow]")
                        audit_table.add_column("Agent / Filter", style="cyan")
                        audit_table.add_column("Result / Output", style="white")

                        audit_table.add_row("Regime Agent", f"{decision.regime_state.regime} (ADX={decision.regime_state.adx_value}, Conf={decision.regime_state.confidence:.0%})")
                        audit_table.add_row("Quant Agent", f"{decision.quant_assessment.action} (P={decision.quant_assessment.probability:.1%}, EV=${decision.quant_assessment.expected_value:.2f})")
                        audit_table.add_row("Macro Agent", f"{decision.macro_context.bias} (Lockout={decision.macro_context.event_lockout})")
                        audit_table.add_row("Decision", f"[bold green]{decision.action}[/bold green] (Score={decision.consensus_score:.2f})")
                        console.print(audit_table)

                        # Risk Validation & Execution
                        if decision.action in ("BUY", "SELL") and decision.proposal:
                            sym_specs = connector.get_symbol_specs(sym)
                            sym_contract_size = sym_specs.get("contract_size", 100.0)

                            console.print(f"[bold cyan]Auditing candidate {decision.action} on {sym} with Risk Engine...[/bold cyan]")
                            approved, reason, calculated_lots = risk_engine.validate_proposal(
                                proposal=decision.proposal,
                                account=account_state,
                                market=market,
                                contract_size=sym_contract_size,
                                sizing_equity=capital,
                            )

                            target_lots = min(calculated_lots, fixed_lots) if (calculated_lots and fixed_lots) else calculated_lots

                            if approved and target_lots:
                                console.print(f"[bold green]RISK APPROVED:[/bold green] Size set to [bold yellow]{target_lots} lots[/bold yellow] (SL: ${decision.proposal.stop_loss:.2f}, TP: ${decision.proposal.take_profit:.2f})")
                                exec_res = gateway.send_order(proposal=decision.proposal, lots=target_lots)
                                if exec_res.success:
                                    console.print(f"[bold green]ORDER FILLED on MT5 Demo:[/bold green] #{exec_res.ticket} {exec_res.action} {exec_res.lots} lots @ ${exec_res.price:.2f}")
                                else:
                                    console.print(f"[bold red]EXECUTION FAILED:[/bold red] {exec_res.message}")
                            else:
                                console.print(f"[bold red]RISK BLOCKED:[/bold red] {reason}")
                        else:
                            console.print(f"[dim]{sym} Decision: HOLD ({decision.audit_trail[-1]})[/dim]")

                except Exception as bar_err:
                    logging.exception("live_trader error on %s", sym)
                    console.print(f"[yellow]Warning [{sym}]:[/yellow] {bar_err}")

            time.sleep(poll_interval)

    except KeyboardInterrupt:
        console.print("\n[bold yellow]Stopping live trader cleanly...[/bold yellow]")
    finally:
        connector.disconnect()
        console.print("[bold cyan]Disconnected from MT5. Shutdown complete.[/bold cyan]")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Live MT5 Demo AI Trader.")
    parser.add_argument("--symbol", type=str, default="XAUUSD", help="Single symbol to trade")
    parser.add_argument("--symbols", nargs="+", default=None, help="List of symbols to scan simultaneously (e.g. --symbols XAUUSD EURUSD GBPUSD)")
    parser.add_argument("--timeframe", type=str, default="H1", help="Timeframe (e.g. H1, H4)")
    parser.add_argument("--poll", type=int, default=5, help="Poll interval in seconds")
    parser.add_argument("--capital", type=float, default=None, help="Size trades as if the account held this much USD")
    parser.add_argument("--lot-size", type=float, default=None, help="Upper cap on the risk engine's lot size")
    args = parser.parse_args()

    active_symbols = args.symbols if args.symbols else [args.symbol]
    run_live_trader(
        symbols=active_symbols,
        timeframe=args.timeframe,
        poll_interval=args.poll,
        capital=args.capital,
        fixed_lots=args.lot_size,
    )

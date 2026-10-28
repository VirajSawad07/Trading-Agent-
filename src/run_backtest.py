"""Backtest Execution CLI Script."""

import argparse
import os
import pandas as pd
import yaml
from rich.console import Console
from rich.table import Table
from src.backtest.engine import BacktestEngine
from src.strategies.baseline_ema import BaselineEMAStrategy
from src.strategies.ml_strategy import MLStrategy


def main():
    parser = argparse.ArgumentParser(description="Run backtest on historical OHLCV data.")
    parser.add_argument("--csv", type=str, default="data/raw/XAUUSD_M15.csv", help="Path to OHLCV CSV file")
    parser.add_argument("--strategy", type=str, default="baseline", choices=["baseline", "ml", "multiagent"], help="Strategy: baseline, ml, or multiagent")
    parser.add_argument("--min-confidence", type=float, default=0.40, help="Confidence threshold for ML/MultiAgent strategy")
    parser.add_argument("--fast", type=int, default=20, help="Fast EMA period")
    parser.add_argument("--slow", type=int, default=50, help="Slow EMA period")
    parser.add_argument("--atr-mult-sl", type=float, default=2.0, help="ATR Stop-Loss multiplier")
    parser.add_argument("--atr-mult-tp", type=float, default=3.0, help="ATR Take-Profit multiplier")
    parser.add_argument("--spread-points", type=float, default=25.0, help="Spread in points (e.g. 25 = $0.25 on gold)")
    args = parser.parse_args()

    if not os.path.exists(args.csv):
        print(f"[Error] Data file not found: {args.csv}. Please run 'python -m src.download_data' first.")
        return

    with open("config/config.yaml", "r") as f:
        config = yaml.safe_load(f)

    print(f"[Backtest] Loading historical data from {args.csv}...")
    df = pd.read_csv(args.csv, index_col=0, parse_dates=True)
    print(f"[Backtest] Loaded {len(df)} candles from {df.index[0]} to {df.index[-1]}.")

    # Initialize Strategy & Generate Signals
    if args.strategy == "multiagent":
        from src.strategies.multi_agent_strategy import MultiAgentStrategy
        print(f"[Backtest] Initializing Hybrid Multi-Agent Consensus Strategy (Quant + Regime + Macro)...")
        strategy = MultiAgentStrategy(
            min_probability=args.min_confidence,
            atr_multiplier_sl=args.atr_mult_sl,
            atr_multiplier_tp=args.atr_mult_tp,
        )
    elif args.strategy == "ml":
        print(f"[Backtest] Initializing Machine Learning Strategy (confidence threshold >= {args.min_confidence})...")
        strategy = MLStrategy(
            min_confidence=args.min_confidence,
            atr_multiplier_sl=args.atr_mult_sl,
            atr_multiplier_tp=args.atr_mult_tp,
        )
    else:
        print(f"[Backtest] Initializing Baseline EMA Strategy (Fast={args.fast}, Slow={args.slow})...")
        strategy = BaselineEMAStrategy(
            fast_period=args.fast,
            slow_period=args.slow,
            atr_multiplier_sl=args.atr_mult_sl,
            atr_multiplier_tp=args.atr_mult_tp,
        )

    df_signals = strategy.generate_signals(df)

    # Initialize Backtest Engine
    engine = BacktestEngine(
        initial_capital=config.get("initial_capital", 10000.0),
        contract_size=config.get("contract_size", 100.0),
        point_size=config.get("point_size", 0.01),
        spread_points=args.spread_points,
        commission_per_lot=config.get("trading_costs", {}).get("commission_per_lot", 7.0),
        slippage_points=config.get("trading_costs", {}).get("slippage_points", 5.0),
    )

    print("[Backtest] Running event-driven simulation...")
    results = engine.run(df_signals, symbol=config.get("symbol", "XAUUSD"))

    # Display Rich Results Table
    console = Console()
    table = Table(title="[bold gold1]Backtest Performance Report (XAU/USD)[/bold gold1]")
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Value", style="bold green")

    metrics = results["metrics"]
    table.add_row("Initial Capital", f"${metrics['initial_capital']:,.2f}")
    table.add_row("Final Capital", f"${metrics['final_capital']:,.2f}")
    
    pnl_style = "bold green" if metrics['total_net_profit'] >= 0 else "bold red"
    table.add_row("Net Profit", f"[{pnl_style}]${metrics['total_net_profit']:,.2f} ({metrics['total_return_pct']:.2f}%)[/{pnl_style}]")
    table.add_row("Total Trades", str(metrics["total_trades"]))
    table.add_row("Win Rate", f"{metrics['win_rate_pct']:.2f}% ({metrics['winning_trades']}W / {metrics['losing_trades']}L)")
    table.add_row("Profit Factor", str(metrics["profit_factor"]))
    table.add_row("Max Drawdown", f"[bold red]{metrics['max_drawdown_pct']:.2f}%[/bold red]")
    table.add_row("Sharpe Ratio", f"{metrics['sharpe_ratio']:.2f}")

    console.print(table)

    # Save reports
    report_file = engine.save_report(results, output_dir=config.get("paths", {}).get("reports_dir", "reports"))
    print(f"[Backtest] Detailed reports saved to {report_file} and reports/equity_curve.csv")


if __name__ == "__main__":
    main()

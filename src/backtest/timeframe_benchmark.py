"""Multi-Timeframe Benchmark Engine for Gold (XAUUSD).

Simulates exact 1:3 Risk-to-Reward trading across all requested timeframes:
- M1  (1-minute)
- M5  (5-minute)
- M15 (15-minute)
- M30 (30-minute / Half an hour)
- H1  (1-hour)
- H4  (4-hour)
- D1  (Daily)

Parameters:
- Symbol: XAUUSD (Gold)
- Lot Size: 0.05 lots (as instructed: 'Lot size 0.05 haleera')
- Risk-to-Reward: Strict 1:3 ratio ('1:3ko ratio mh')
- Broker Friction: Spread = 25 pts ($0.25), Commission = $7/lot, Slippage = 5 pts
"""

import os
from typing import Dict, List
import pandas as pd
import numpy as np
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from src.data.mt5_connector import MT5Connector, TIMEFRAME_MAP
from src.features.indicators import calculate_atr, calculate_ema, calculate_rsi
from src.backtest.engine import BacktestEngine


def generate_1to3_signals(df: pd.DataFrame, rr_ratio: float = 3.0) -> pd.DataFrame:
    """Generates trend-momentum entry signals with strict 1:3 Risk-to-Reward SL/TP."""
    df = df.copy()
    close = df["close"]
    
    # EMAs for trend identification
    ema_fast = calculate_ema(close, 20)
    ema_slow = calculate_ema(close, 50)
    atr = calculate_atr(df, 14)
    rsi = calculate_rsi(close, 14)

    # Bullish crossover or strong momentum breakout
    prev_fast = ema_fast.shift(1)
    prev_slow = ema_slow.shift(1)
    
    bull_signal = (prev_fast <= prev_slow) & (ema_fast > ema_slow) & (rsi >= 45) & (rsi <= 70)
    bear_signal = (prev_fast >= prev_slow) & (ema_fast < ema_slow) & (rsi <= 55) & (rsi >= 30)

    signals = pd.Series(0, index=df.index)
    signals[bull_signal] = 1
    signals[bear_signal] = -1

    df["signal"] = signals
    df["sl_price"] = np.nan
    df["tp_price"] = np.nan

    # Strict 1:3 Risk to Reward Ratio
    # Stop Loss = 1.0 * ATR
    # Take Profit = 3.0 * ATR (1:3 ratio)
    sl_mult = 1.0
    tp_mult = sl_mult * rr_ratio

    buy_mask = df["signal"] == 1
    df.loc[buy_mask, "sl_price"] = close[buy_mask] - (sl_mult * atr[buy_mask])
    df.loc[buy_mask, "tp_price"] = close[buy_mask] + (tp_mult * atr[buy_mask])

    sell_mask = df["signal"] == -1
    df.loc[sell_mask, "sl_price"] = close[sell_mask] + (sl_mult * atr[sell_mask])
    df.loc[sell_mask, "tp_price"] = close[sell_mask] - (tp_mult * atr[sell_mask])

    return df


def benchmark_all_timeframes(
    symbol: str = "XAUUSD",
    fixed_lots: float = 0.05,
    target_trades: int = 100,
):
    console = Console()
    console.print(Panel.fit(
        f"[bold gold1]XAU/USD Gold Multi-Timeframe Benchmark Desk[/bold gold1]\n"
        f"[cyan]Testing: M1, M5, M15, M30, H1, H4, D1 | Volume: {fixed_lots} Lots | Risk-Reward: 1:3[/cyan]"
    ))

    connector = MT5Connector()
    mt5_online = connector.connect()
    if not mt5_online:
        console.print("[yellow]MT5 terminal offline or unauthorized. Utilizing local tick/OHLCV datasets with multi-timeframe resampling...[/yellow]")

    timeframes = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]
    results = []

    # Pre-load local files if MT5 offline
    df_m15_local = None
    df_m5_local = None
    if os.path.exists("data/raw/XAUUSD_M15.csv"):
        df_m15_local = pd.read_csv("data/raw/XAUUSD_M15.csv", index_col=0, parse_dates=True)
    if os.path.exists("data/raw/XAUUSD_M5.csv"):
        df_m5_local = pd.read_csv("data/raw/XAUUSD_M5.csv", index_col=0, parse_dates=True)

    agg_dict = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}

    for tf in timeframes:
        console.print(f"[cyan]Benchmarking {symbol} on [bold yellow]{tf}[/bold yellow]...[/cyan]")
        try:
            df = None
            if mt5_online:
                try:
                    df = connector.fetch_historical_bars(symbol=symbol, timeframe_str=tf, bars_count=8000)
                except Exception:
                    df = None

            # Local fallback / Resampling
            if df is None:
                if tf == "M5" and df_m5_local is not None:
                    df = df_m5_local.copy()
                elif tf == "M15" and df_m15_local is not None:
                    df = df_m15_local.copy()
                elif tf == "M30" and df_m15_local is not None:
                    df = df_m15_local.resample("30min").agg(agg_dict).dropna()
                elif tf == "H1" and df_m15_local is not None:
                    df = df_m15_local.resample("1h").agg(agg_dict).dropna()
                elif tf == "H4" and df_m15_local is not None:
                    df = df_m15_local.resample("4h").agg(agg_dict).dropna()
                elif tf == "D1" and df_m15_local is not None:
                    df = df_m15_local.resample("1D").agg(agg_dict).dropna()
                elif tf == "M1":
                    # Generate high-resolution M1 sample from MT5Connector
                    df = MT5Connector.generate_sample_gold_data(bars_count=8000, freq="1min")

            if df is None or len(df) < 50:
                console.print(f"[yellow]Insufficient data for {tf}. Skipping.[/yellow]")
                continue

            df_signals = generate_1to3_signals(df, rr_ratio=3.0)

            # Custom Backtest Engine with fixed 0.05 lots
            engine = BacktestEngine(
                initial_capital=100000.0,
                contract_size=100.0,
                point_size=0.01,
                spread_points=25.0,     # $0.25 spread
                commission_per_lot=7.0, # $7/lot
                slippage_points=5.0,    # $0.05 slippage
            )

            # Force fixed 0.05 lots in risk engine
            engine.risk_engine.max_risk_per_trade_pct = 0.05
            engine.risk_engine.min_lot_size = fixed_lots
            engine.risk_engine.max_lot_size = fixed_lots

            res = engine.run(df_signals, symbol=symbol)

            trades_list = res.get("trades", [])
            total_trades = len(trades_list)
            if total_trades == 0:
                continue

            metrics = res.get("metrics", {})
            winning_trades = metrics.get("winning_trades", 0)
            losing_trades = metrics.get("losing_trades", 0)
            win_rate = metrics.get("win_rate_pct", 0.0)
            net_profit = metrics.get("total_net_profit", 0.0)
            profit_factor = metrics.get("profit_factor", 0.0)
            max_dd_pct = metrics.get("max_drawdown_pct", 0.0)

            # Calculate average win / loss
            pnls = [t["net_pnl"] if isinstance(t, dict) else t.net_pnl for t in trades_list]
            win_pnls = [p for p in pnls if p > 0]
            loss_pnls = [abs(p) for p in pnls if p < 0]
            avg_win = float(np.mean(win_pnls)) if win_pnls else 0.0
            avg_loss = float(np.mean(loss_pnls)) if loss_pnls else 0.0

            results.append({
                "timeframe": tf,
                "bars": len(df),
                "trades": total_trades,
                "wins": winning_trades,
                "losses": losing_trades,
                "win_rate": win_rate,
                "profit_factor": profit_factor,
                "net_profit": net_profit,
                "avg_win": avg_win,
                "avg_loss": avg_loss,
                "max_dd_pct": max_dd_pct,
            })

        except Exception as e:
            console.print(f"[red]Error benchmarking {tf}: {e}[/red]")

    connector.disconnect()

    # Display Consolidated Comparison Table
    table = Table(title="[bold gold1]Gold (XAUUSD) Multi-Timeframe Performance Benchmark (1:3 Ratio, 0.05 Lots)[/bold gold1]")
    table.add_column("Timeframe", style="bold cyan")
    table.add_column("Trades", justify="right")
    table.add_column("Wins", justify="right", style="green")
    table.add_column("Losses", justify="right", style="red")
    table.add_column("Win Rate (%)", justify="right", style="bold yellow")
    table.add_column("Profit Factor", justify="right")
    table.add_column("Avg Win ($)", justify="right", style="green")
    table.add_column("Avg Loss ($)", justify="right", style="red")
    table.add_column("Net Profit ($)", justify="right", style="bold green")
    table.add_column("Max DD (%)", justify="right", style="magenta")

    for r in results:
        pnl_style = "bold green" if r["net_profit"] >= 0 else "bold red"
        pnl_str = f"+${r['net_profit']:,.2f}" if r["net_profit"] >= 0 else f"-${abs(r['net_profit']):,.2f}"
        table.add_row(
            r["timeframe"],
            str(r["trades"]),
            str(r["wins"]),
            str(r["losses"]),
            f"{r['win_rate']:.1f}%",
            f"{r['profit_factor']:.2f}",
            f"${r['avg_win']:.2f}",
            f"${r['avg_loss']:.2f}",
            f"[{pnl_style}]{pnl_str}[/{pnl_style}]",
            f"{r['max_dd_pct']:.2f}%",
        )

    console.print()
    console.print(table)
    return results


if __name__ == "__main__":
    benchmark_all_timeframes()

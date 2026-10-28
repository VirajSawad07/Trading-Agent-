"""Event-Driven & Realistic Backtesting Engine.

Models real-world broker friction:
- Bid/Ask Spread expansion
- Commission per lot
- Slippage
- Intrabar Stop-Loss and Take-Profit execution
- Integrated Risk Engine limits & Circuit Breakers
"""

import json
import math
import os
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional
import numpy as np
import pandas as pd
from src.risk.risk_engine import AccountState, MarketConditions, OrderProposal, RiskEngine


@dataclass
class TradeRecord:
    trade_id: int
    symbol: str
    action: str
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    lots: float
    pnl: float
    net_pnl: float
    commission: float
    slippage: float
    exit_reason: str     # "SL", "TP", "REVERSE", "END_OF_DATA"


class BacktestEngine:
    def __init__(
        self,
        initial_capital: float = 10000.0,
        contract_size: float = 100.0,
        point_size: float = 0.01,
        spread_points: float = 25.0,
        commission_per_lot: float = 7.0,
        slippage_points: float = 5.0,
        risk_config_path: str = "config/risk_limits.yaml",
    ):
        self.initial_capital = initial_capital
        self.contract_size = contract_size
        self.point_size = point_size
        self.spread_points = spread_points
        self.commission_per_lot = commission_per_lot
        self.slippage_points = slippage_points
        self.risk_engine = RiskEngine(config_path=risk_config_path)

    def run(self, df: pd.DataFrame, symbol: str = "XAUUSD") -> Dict:
        """Executes chronological simulation on bar data."""
        df = df.copy()
        if "signal" not in df.columns:
            raise ValueError("DataFrame must contain a 'signal' column before running backtest.")

        capital = self.initial_capital
        equity = capital
        trades: List[TradeRecord] = []
        equity_curve: List[Dict] = []
        
        active_trade: Optional[Dict] = None
        trade_counter = 0

        # Track daily equity for daily circuit breaker
        current_day = None
        daily_start_equity = capital

        timestamps = df.index if isinstance(df.index, pd.DatetimeIndex) else pd.to_datetime(df["time"])

        for i in range(len(df)):
            bar = df.iloc[i]
            bar_time = timestamps[i]
            bar_day = bar_time.date()

            # Handle new trading day reset
            if current_day != bar_day:
                current_day = bar_day
                daily_start_equity = equity
                self.risk_engine.reset_kill_switch()

            bar_open = float(bar["open"])
            bar_high = float(bar["high"])
            bar_low = float(bar["low"])
            bar_close = float(bar["close"])
            signal = int(bar.get("signal", 0))

            spread_cost = self.spread_points * self.point_size
            slippage_cost = self.slippage_points * self.point_size

            # 1. Manage Active Trade (Check TP / SL intrabar)
            if active_trade is not None:
                is_buy = active_trade["action"] == "BUY"
                sl = active_trade["sl"]
                tp = active_trade["tp"]
                lots = active_trade["lots"]
                entry_price = active_trade["entry_price"]

                exit_price = None
                exit_reason = None

                if is_buy:
                    if bar_low <= sl:
                        exit_price = sl - slippage_cost
                        exit_reason = "SL"
                    elif bar_high >= tp:
                        exit_price = tp - slippage_cost
                        exit_reason = "TP"
                    elif signal == -1:  # Opposite signal reversal
                        exit_price = bar_open - slippage_cost
                        exit_reason = "REVERSE"
                else:  # Active SELL
                    if bar_high >= sl:
                        exit_price = sl + slippage_cost
                        exit_reason = "SL"
                    elif bar_low <= tp:
                        exit_price = tp + slippage_cost
                        exit_reason = "TP"
                    elif signal == 1:   # Opposite signal reversal
                        exit_price = bar_open + slippage_cost
                        exit_reason = "REVERSE"

                if exit_price is not None:
                    # Calculate PnL
                    price_diff = (exit_price - entry_price) if is_buy else (entry_price - exit_price)
                    gross_pnl = price_diff * self.contract_size * lots
                    comm = self.commission_per_lot * lots
                    net_pnl = gross_pnl - comm

                    capital += net_pnl
                    equity = capital

                    trades.append(
                        TradeRecord(
                            trade_id=active_trade["trade_id"],
                            symbol=symbol,
                            action=active_trade["action"],
                            entry_time=str(active_trade["entry_time"]),
                            exit_time=str(bar_time),
                            entry_price=entry_price,
                            exit_price=exit_price,
                            lots=lots,
                            pnl=round(gross_pnl, 2),
                            net_pnl=round(net_pnl, 2),
                            commission=round(comm, 2),
                            slippage=round(slippage_cost * self.contract_size * lots, 2),
                            exit_reason=exit_reason,
                        )
                    )
                    active_trade = None

            # 2. Check for New Trade Entry
            if active_trade is None and signal in (1, -1):
                action = "BUY" if signal == 1 else "SELL"
                sl_price = float(bar.get("sl_price", 0.0))
                tp_price = float(bar.get("tp_price", 0.0))

                # Entry execution on next bar open or current close with spread + slippage
                if action == "BUY":
                    fill_price = bar_close + spread_cost + slippage_cost
                else:
                    fill_price = bar_close - spread_cost - slippage_cost

                proposal = OrderProposal(
                    symbol=symbol,
                    action=action,
                    entry_price=fill_price,
                    stop_loss=sl_price,
                    take_profit=tp_price,
                    strategy_id="Baseline",
                )

                account = AccountState(
                    balance=capital,
                    equity=equity,
                    open_positions=1 if active_trade else 0,
                    daily_starting_equity=daily_start_equity,
                    is_demo=True,
                )

                market = MarketConditions(
                    current_spread_points=self.spread_points,
                    bid=bar_close,
                    ask=bar_close + spread_cost,
                )

                approved, reason, lots = self.risk_engine.validate_proposal(
                    proposal=proposal,
                    account=account,
                    market=market,
                    contract_size=self.contract_size,
                )

                if approved and lots and lots > 0:
                    trade_counter += 1
                    active_trade = {
                        "trade_id": trade_counter,
                        "action": action,
                        "entry_time": bar_time,
                        "entry_price": fill_price,
                        "sl": sl_price,
                        "tp": tp_price,
                        "lots": lots,
                    }

            # Record periodic equity curve
            equity_curve.append(
                {
                    "time": str(bar_time),
                    "capital": round(capital, 2),
                    "equity": round(equity, 2),
                }
            )

        # Calculate institutional statistics
        metrics = self._calculate_metrics(capital, trades, equity_curve)
        return {
            "metrics": metrics,
            "trades": [asdict(t) for t in trades],
            "equity_curve": equity_curve,
        }

    def _calculate_metrics(
        self, final_capital: float, trades: List[TradeRecord], equity_curve: List[Dict]
    ) -> Dict:
        total_net_profit = final_capital - self.initial_capital
        total_return_pct = (total_net_profit / self.initial_capital) * 100.0

        if not trades:
            return {
                "initial_capital": self.initial_capital,
                "final_capital": final_capital,
                "total_net_profit": total_net_profit,
                "total_return_pct": total_return_pct,
                "total_trades": 0,
                "win_rate_pct": 0.0,
                "profit_factor": 0.0,
                "max_drawdown_pct": 0.0,
                "sharpe_ratio": 0.0,
            }

        pnls = [t.net_pnl for t in trades]
        winning_trades = [p for p in pnls if p > 0]
        losing_trades = [p for p in pnls if p <= 0]

        win_rate = (len(winning_trades) / len(trades)) * 100.0
        gross_profit = sum(winning_trades)
        gross_loss = abs(sum(losing_trades))
        profit_factor = round(gross_profit / (gross_loss + 1e-9), 2)

        # Maximum Drawdown calculation from equity curve
        eq_series = pd.Series([point["equity"] for point in equity_curve])
        running_max = eq_series.cummax()
        drawdowns = (running_max - eq_series) / running_max
        max_drawdown_pct = float(drawdowns.max() * 100.0)

        # Daily returns & Sharpe Ratio (assuming 252 trading days / year)
        eq_df = pd.DataFrame(equity_curve)
        eq_df["time"] = pd.to_datetime(eq_df["time"])
        daily_equity = eq_df.set_index("time")["equity"].resample("1D").last().dropna()
        daily_returns = daily_equity.pct_change().dropna()

        if len(daily_returns) > 1 and daily_returns.std() > 0:
            sharpe_ratio = float((daily_returns.mean() / daily_returns.std()) * math.sqrt(252))
        else:
            sharpe_ratio = 0.0

        return {
            "initial_capital": self.initial_capital,
            "final_capital": round(final_capital, 2),
            "total_net_profit": round(total_net_profit, 2),
            "total_return_pct": round(total_return_pct, 2),
            "total_trades": len(trades),
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "win_rate_pct": round(win_rate, 2),
            "profit_factor": profit_factor,
            "max_drawdown_pct": round(max_drawdown_pct, 2),
            "sharpe_ratio": round(sharpe_ratio, 2),
            "avg_trade_pnl": round(float(np.mean(pnls)), 2),
        }

    def save_report(self, results: Dict, output_dir: str = "reports") -> str:
        os.makedirs(output_dir, exist_ok=True)
        report_path = os.path.join(output_dir, "backtest_summary.json")
        equity_path = os.path.join(output_dir, "equity_curve.csv")

        with open(report_path, "w") as f:
            json.dump(results["metrics"], f, indent=4)

        pd.DataFrame(results["equity_curve"]).to_csv(equity_path, index=False)
        return report_path

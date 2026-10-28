"""Baseline Strategy: Dual EMA Trend Following with Dynamic ATR Stops."""

import numpy as np
import pandas as pd
from src.features.indicators import generate_baseline_features
from src.strategies.base import BaseStrategy


class BaselineEMAStrategy(BaseStrategy):
    def __init__(
        self,
        fast_period: int = 20,
        slow_period: int = 50,
        atr_period: int = 14,
        atr_multiplier_sl: float = 2.0,
        atr_multiplier_tp: float = 3.0,
        filter_session: bool = True,
    ):
        super().__init__(name="Baseline_EMA_ATR")
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.atr_period = atr_period
        self.atr_multiplier_sl = atr_multiplier_sl
        self.atr_multiplier_tp = atr_multiplier_tp
        self.filter_session = filter_session

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = generate_baseline_features(
            df,
            fast_period=self.fast_period,
            slow_period=self.slow_period,
            atr_period=self.atr_period,
        )

        # Detect crossover:
        # Fast EMA was below slow EMA previous bar, now above
        prev_fast = df["ema_fast"].shift(1)
        prev_slow = df["ema_slow"].shift(1)
        curr_fast = df["ema_fast"]
        curr_slow = df["ema_slow"]

        bullish_crossover = (prev_fast <= prev_slow) & (curr_fast > curr_slow)
        bearish_crossover = (prev_fast >= prev_slow) & (curr_fast < curr_slow)

        signals = pd.Series(0, index=df.index)
        signals[bullish_crossover] = 1
        signals[bearish_crossover] = -1

        # Optional session filter: Gold is best traded when London or NY is open
        if self.filter_session and "session_london" in df.columns:
            active_sessions = (df["session_london"] == 1) | (df["session_newyork"] == 1)
            signals = signals.where(active_sessions, 0)

        df["signal"] = signals

        # Calculate dynamic stop loss and take profit levels
        atr = df["atr"]
        close = df["close"]

        df["sl_price"] = np.nan
        df["tp_price"] = np.nan

        buy_mask = df["signal"] == 1
        df.loc[buy_mask, "sl_price"] = close[buy_mask] - (self.atr_multiplier_sl * atr[buy_mask])
        df.loc[buy_mask, "tp_price"] = close[buy_mask] + (self.atr_multiplier_tp * atr[buy_mask])

        sell_mask = df["signal"] == -1
        df.loc[sell_mask, "sl_price"] = close[sell_mask] + (self.atr_multiplier_sl * atr[sell_mask])
        df.loc[sell_mask, "tp_price"] = close[sell_mask] - (self.atr_multiplier_tp * atr[sell_mask])

        return df

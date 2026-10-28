"""Market Regime Classification Agent."""

from dataclasses import dataclass
from typing import Dict, Optional
import numpy as np
import pandas as pd
from src.features.indicators import calculate_adx, calculate_atr, calculate_bollinger_bands, calculate_ema


@dataclass
class RegimeState:
    regime: str             # "TRENDING_BULL", "TRENDING_BEAR", "RANGING", "HIGH_VOLATILITY"
    confidence: float       # 0.0 to 1.0
    allow_buy: bool
    allow_sell: bool
    volatility_level: str   # "LOW", "NORMAL", "EXTREME"
    adx_value: float
    reason: str


class RegimeAgent:
    """Agent responsible for determining current market regime and directional policy."""

    def __init__(self, adx_trend_threshold: float = 25.0, adx_range_threshold: float = 20.0):
        self.adx_trend_threshold = adx_trend_threshold
        self.adx_range_threshold = adx_range_threshold

    def analyze(self, df: pd.DataFrame) -> RegimeState:
        if len(df) < 50:
            return RegimeState(
                regime="RANGING",
                confidence=0.5,
                allow_buy=True,
                allow_sell=True,
                volatility_level="NORMAL",
                adx_value=15.0,
                reason="Insufficient history for robust regime classification.",
            )

        close = df["close"]
        ema_20 = calculate_ema(close, 20).iloc[-1]
        ema_50 = calculate_ema(close, 50).iloc[-1]
        last_close = close.iloc[-1]

        # ADX trend strength
        adx_df = calculate_adx(df, period=14)
        current_adx = float(adx_df["adx"].iloc[-1])
        plus_di = float(adx_df["plus_di"].iloc[-1])
        minus_di = float(adx_df["minus_di"].iloc[-1])

        # ATR Volatility check
        atr = calculate_atr(df, period=14)
        atr_ratio = float(atr.iloc[-1] / (last_close + 1e-9))
        historical_atr_ratios = atr / (close + 1e-9)
        vol_percentile = float((historical_atr_ratios < atr_ratio).mean() * 100.0)

        # 1. Extreme Volatility Regime (news spikes or liquidity collapse)
        if vol_percentile >= 92.0:
            return RegimeState(
                regime="HIGH_VOLATILITY",
                confidence=round(vol_percentile / 100.0, 2),
                allow_buy=False,
                allow_sell=False,
                volatility_level="EXTREME",
                adx_value=round(current_adx, 2),
                reason=f"Volatility in 92nd+ percentile ({vol_percentile:.1f}%). High slippage risk; lock trading.",
            )

        # 2. Strong Bullish Trend
        if current_adx >= self.adx_trend_threshold and ema_20 > ema_50 and plus_di > minus_di:
            conf = min(0.95, 0.60 + (current_adx / 100.0))
            return RegimeState(
                regime="TRENDING_BULL",
                confidence=round(conf, 2),
                allow_buy=True,
                allow_sell=False,
                volatility_level="NORMAL",
                adx_value=round(current_adx, 2),
                reason=f"Bullish trend confirmed (ADX={current_adx:.1f}, +DI > -DI, Price > EMA50).",
            )

        # 3. Strong Bearish Trend
        if current_adx >= self.adx_trend_threshold and ema_20 < ema_50 and minus_di > plus_di:
            conf = min(0.95, 0.60 + (current_adx / 100.0))
            return RegimeState(
                regime="TRENDING_BEAR",
                confidence=round(conf, 2),
                allow_buy=False,
                allow_sell=True,
                volatility_level="NORMAL",
                adx_value=round(current_adx, 2),
                reason=f"Bearish trend confirmed (ADX={current_adx:.1f}, -DI > +DI, Price < EMA50).",
            )

        # 4. Ranging / Sideways Consolidation
        bb = calculate_bollinger_bands(close, period=20, num_std=2.0)
        bandwidth = float(bb["bb_bandwidth"].iloc[-1])
        vol_lvl = "LOW" if vol_percentile < 25.0 else "NORMAL"

        return RegimeState(
            regime="RANGING",
            confidence=0.75,
            allow_buy=True,
            allow_sell=True,
            volatility_level=vol_lvl,
            adx_value=round(current_adx, 2),
            reason=f"Market consolidating sideways (ADX={current_adx:.1f} < {self.adx_trend_threshold}).",
        )

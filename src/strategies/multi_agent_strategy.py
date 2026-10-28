"""High-Performance Multi-Agent Strategy combining Quant Model, Regime Analysis, and Macro Reasoning."""

import numpy as np
import pandas as pd
from src.features.alpha_features import compute_alpha_features, get_feature_columns
from src.features.indicators import calculate_adx, calculate_atr, calculate_ema
from src.orchestration.coordinator import DecisionCoordinator
from src.strategies.base import BaseStrategy


class MultiAgentStrategy(BaseStrategy):
    """Strategy that executes trades only when Quant, Regime, and Macro agents reach consensus."""

    def __init__(
        self,
        model_path: str = "models/ml/lightgbm_gold_m15.pkl",
        min_probability: float = 0.40,
        atr_multiplier_sl: float = 2.0,
        atr_multiplier_tp: float = 3.0,
    ):
        super().__init__(name="MultiAgent_Consensus_Strategy")
        self.coordinator = DecisionCoordinator()
        self.coordinator.quant_agent.min_probability = min_probability
        self.coordinator.quant_agent.atr_multiplier_sl = atr_multiplier_sl
        self.coordinator.quant_agent.atr_multiplier_tp = atr_multiplier_tp
        self.min_probability = min_probability
        self.atr_multiplier_sl = atr_multiplier_sl
        self.atr_multiplier_tp = atr_multiplier_tp

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        total_bars = len(df)
        min_warmup = 50

        # Vectorized Precomputation for ultra-fast simulation
        featured_df = compute_alpha_features(df)
        feature_names = self.coordinator.quant_agent.feature_names
        X = featured_df[feature_names].fillna(0)

        # Quant Model Probabilities
        if self.coordinator.quant_agent.model is not None:
            probs = self.coordinator.quant_agent.model.predict_proba(X)
            prob_buy_series = probs[:, 1]
            prob_sell_series = probs[:, 2]
        else:
            prob_buy_series = np.zeros(total_bars)
            prob_sell_series = np.zeros(total_bars)

        # Regime Indicators Precomputation
        close = df["close"]
        adx_df = calculate_adx(df, 14)
        adx_series = adx_df["adx"].values
        plus_di_series = adx_df["plus_di"].values
        minus_di_series = adx_df["minus_di"].values
        ema_20_series = calculate_ema(close, 20).values
        ema_50_series = calculate_ema(close, 50).values
        atr_series = calculate_atr(df, 14).values

        # ATR Volatility Percentile calculation
        historical_atr_ratios = atr_series / (close.values + 1e-9)

        # Timestamps for Macro Agent
        timestamps = df.index if isinstance(df.index, pd.DatetimeIndex) else pd.to_datetime(df["time"])
        hours = timestamps.hour.values
        weekdays = timestamps.weekday.values

        signals = np.zeros(total_bars, dtype=int)
        sl_prices = np.full(total_bars, np.nan)
        tp_prices = np.full(total_bars, np.nan)
        consensus_scores = np.zeros(total_bars)

        for i in range(min_warmup, total_bars):
            # 1. Macro Lockout Check (Friday evening close)
            if weekdays[i] == 4 and hours[i] >= 20:
                continue

            # 2. Extreme Volatility Lockout Check (top 92nd percentile)
            # Use rolling window up to i to avoid lookahead
            current_atr_ratio = historical_atr_ratios[i]
            prior_ratios = historical_atr_ratios[max(0, i - 500) : i + 1]
            vol_percentile = (prior_ratios < current_atr_ratio).mean() * 100.0
            if vol_percentile >= 92.0:
                continue

            # 3. Regime Evaluation
            curr_adx = adx_series[i]
            p_di = plus_di_series[i]
            m_di = minus_di_series[i]
            e20 = ema_20_series[i]
            e50 = ema_50_series[i]

            is_bull_trend = curr_adx >= 25.0 and e20 > e50 and p_di > m_di
            is_bear_trend = curr_adx >= 25.0 and e20 < e50 and m_di > p_di
            allow_buy = is_bull_trend or curr_adx < 25.0  # Allow buy in bull trend or range
            allow_sell = is_bear_trend or curr_adx < 25.0 # Allow sell in bear trend or range

            # 4. Quant Model Evaluation
            p_buy = prob_buy_series[i]
            p_sell = prob_sell_series[i]
            atr_val = atr_series[i]
            curr_close = close.iloc[i]

            reward_dist = self.atr_multiplier_tp * atr_val
            risk_dist = self.atr_multiplier_sl * atr_val

            # Consensus BUY check
            if p_buy >= self.min_probability and p_buy > p_sell and allow_buy:
                signals[i] = 1
                sl_prices[i] = round(curr_close - risk_dist, 2)
                tp_prices[i] = round(curr_close + reward_dist, 2)
                consensus_scores[i] = round(p_buy * 0.70 + (0.30 if is_bull_trend else 0.15), 2)

            # Consensus SELL check
            elif p_sell >= self.min_probability and p_sell > p_buy and allow_sell:
                signals[i] = -1
                sl_prices[i] = round(curr_close + risk_dist, 2)
                tp_prices[i] = round(curr_close - reward_dist, 2)
                consensus_scores[i] = round(p_sell * 0.70 + (0.30 if is_bear_trend else 0.15), 2)

        featured_df["signal"] = signals
        featured_df["sl_price"] = sl_prices
        featured_df["tp_price"] = tp_prices
        featured_df["consensus_score"] = consensus_scores

        return featured_df

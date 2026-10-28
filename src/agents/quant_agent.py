"""Quantitative Model Analysis and Expected Value (EV) Agent."""

import os
from dataclasses import dataclass
from typing import Optional
import joblib
import numpy as np
import pandas as pd
from src.features.alpha_features import compute_alpha_features, get_feature_columns
from src.features.indicators import calculate_atr


@dataclass
class QuantAssessment:
    action: str              # "BUY", "SELL", "HOLD"
    probability: float       # Predicted model probability
    expected_value: float    # Dollar EV per 1.0 lot
    confidence_pass: bool    # True if probability >= min_threshold and EV > 0
    suggested_sl: float
    suggested_tp: float
    reason: str


class QuantAgent:
    """Agent that calculates statistical trade probabilities and mathematically verifies Expected Value."""

    def __init__(
        self,
        model_path: Optional[str] = None,
        timeframe: str = "M5",
        min_probability: float = 0.34,
        directional_dominance_ratio: float = 0.55,
        atr_multiplier_sl: float = 2.0,
        atr_multiplier_tp: float = 3.0,
        contract_size: float = 100.0,
    ):
        if model_path is None:
            m5_path = "models/ml/lightgbm_gold_m5.pkl"
            m15_path = "models/ml/lightgbm_gold_m15.pkl"
            if timeframe.upper() == "M5" and os.path.exists(m5_path):
                model_path = m5_path
            elif os.path.exists(m15_path):
                model_path = m15_path
            else:
                model_path = m5_path if os.path.exists(m5_path) else m15_path

        self.model_path = model_path
        self.timeframe = timeframe
        self.min_probability = min_probability
        self.directional_dominance_ratio = directional_dominance_ratio
        self.atr_multiplier_sl = atr_multiplier_sl
        self.atr_multiplier_tp = atr_multiplier_tp
        self.contract_size = contract_size

        if os.path.exists(model_path):
            artifact = joblib.load(model_path)
            self.model = artifact["model"]
            self.feature_names = artifact["feature_names"]
        else:
            self.model = None
            self.feature_names = get_feature_columns()

    def evaluate_bar(
        self,
        df_history: pd.DataFrame,
        spread_points: float = 25.0,
        commission_per_lot: float = 7.0,
        slippage_points: float = 5.0,
    ) -> QuantAssessment:
        if self.model is None:
            return QuantAssessment(
                action="HOLD",
                probability=0.0,
                expected_value=0.0,
                confidence_pass=False,
                suggested_sl=0.0,
                suggested_tp=0.0,
                reason="Trained ML model not loaded.",
            )

        featured_df = compute_alpha_features(df_history)
        atr_series = calculate_atr(featured_df, 14)
        atr = float(atr_series.iloc[-1])
        close = float(df_history["close"].iloc[-1])

        # Extract latest feature vector
        latest_features = featured_df[self.feature_names].iloc[[-1]].fillna(0)
        probs = self.model.predict_proba(latest_features)[0]

        prob_hold, prob_buy, prob_sell = float(probs[0]), float(probs[1]), float(probs[2])

        # Directional mass ratio
        directional_mass = prob_buy + prob_sell + 1e-9
        buy_ratio = prob_buy / directional_mass
        sell_ratio = prob_sell / directional_mass

        # Total estimated friction per 1.0 lot ($)
        point_value = 0.01 * self.contract_size  # $1.00 per point on standard 100oz gold lot
        friction_cost = (spread_points * point_value) + (slippage_points * point_value) + commission_per_lot

        reward_distance = self.atr_multiplier_tp * atr
        risk_distance = self.atr_multiplier_sl * atr

        reward_dollars = reward_distance * self.contract_size
        risk_dollars = risk_distance * self.contract_size

        # Check BUY setup
        if prob_buy >= prob_sell and (prob_buy >= self.min_probability or buy_ratio >= self.directional_dominance_ratio):
            ev = (prob_buy * reward_dollars) - ((1.0 - prob_buy) * risk_dollars) - friction_cost
            sl = round(close - risk_distance, 2)
            tp = round(close + reward_distance, 2)
            pass_check = (ev > 0 or buy_ratio >= self.directional_dominance_ratio) and prob_buy >= 0.28
            return QuantAssessment(
                action="BUY",
                probability=round(prob_buy, 4),
                expected_value=round(ev, 2),
                confidence_pass=pass_check,
                suggested_sl=sl,
                suggested_tp=tp,
                reason=f"BUY signal P={prob_buy:.1%} (Dominance={buy_ratio:.1%}), Net EV=${ev:.2f}/lot",
            )

        # Check SELL setup
        if prob_sell > prob_buy and (prob_sell >= self.min_probability or sell_ratio >= self.directional_dominance_ratio):
            ev = (prob_sell * reward_dollars) - ((1.0 - prob_sell) * risk_dollars) - friction_cost
            sl = round(close + risk_distance, 2)
            tp = round(close - reward_distance, 2)
            pass_check = (ev > 0 or sell_ratio >= self.directional_dominance_ratio) and prob_sell >= 0.28
            return QuantAssessment(
                action="SELL",
                probability=round(prob_sell, 4),
                expected_value=round(ev, 2),
                confidence_pass=pass_check,
                suggested_sl=sl,
                suggested_tp=tp,
                reason=f"SELL signal P={prob_sell:.1%} (Dominance={sell_ratio:.1%}), Net EV=${ev:.2f}/lot",
            )

        return QuantAssessment(
            action="HOLD",
            probability=round(prob_hold, 4),
            expected_value=0.0,
            confidence_pass=False,
            suggested_sl=0.0,
            suggested_tp=0.0,
            reason=f"No statistically significant directional edge (Hold P={prob_hold:.1%})",
        )

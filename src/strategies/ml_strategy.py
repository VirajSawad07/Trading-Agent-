"""Machine Learning Signal Strategy utilizing LightGBM Probability Forecasting."""

import os
import joblib
import numpy as np
import pandas as pd
from src.features.alpha_features import compute_alpha_features, get_feature_columns
from src.features.indicators import calculate_atr
from src.strategies.base import BaseStrategy


class MLStrategy(BaseStrategy):
    def __init__(
        self,
        model_path: str = "models/ml/lightgbm_gold_m15.pkl",
        min_confidence: float = 0.45,
        atr_period: int = 14,
        atr_multiplier_sl: float = 2.0,
        atr_multiplier_tp: float = 3.0,
    ):
        super().__init__(name="ML_LightGBM_Strategy")
        self.model_path = model_path
        self.min_confidence = min_confidence
        self.atr_period = atr_period
        self.atr_multiplier_sl = atr_multiplier_sl
        self.atr_multiplier_tp = atr_multiplier_tp
        self.model_artifact = None

        if os.path.exists(model_path):
            self.model_artifact = joblib.load(model_path)
            self.model = self.model_artifact["model"]
            self.feature_names = self.model_artifact["feature_names"]
        else:
            self.model = None
            self.feature_names = get_feature_columns()

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        if self.model is None:
            raise RuntimeError(f"Trained model not found at {self.model_path}. Run 'python -m src.models.train_ml' first.")

        df = df.copy()
        featured_df = compute_alpha_features(df)
        atr = calculate_atr(featured_df, period=self.atr_period)
        featured_df["atr"] = atr

        # Extract features matrix
        X = featured_df[self.feature_names].fillna(0)

        # Predict probability distributions across [HOLD, BUY, SELL]
        probs = self.model.predict_proba(X)
        
        # Probabilities
        prob_buy = probs[:, 1]
        prob_sell = probs[:, 2]

        signals = pd.Series(0, index=df.index)
        
        # Signal triggers when confidence exceeds threshold
        buy_cond = prob_buy >= self.min_confidence
        sell_cond = prob_sell >= self.min_confidence

        signals[buy_cond] = 1
        signals[sell_cond] = -1

        featured_df["signal"] = signals
        featured_df["prob_buy"] = np.round(prob_buy, 4)
        featured_df["prob_sell"] = np.round(prob_sell, 4)

        # Dynamic ATR Stop Loss & Take Profit
        close = featured_df["close"]
        featured_df["sl_price"] = np.nan
        featured_df["tp_price"] = np.nan

        buy_mask = featured_df["signal"] == 1
        featured_df.loc[buy_mask, "sl_price"] = close[buy_mask] - (self.atr_multiplier_sl * atr[buy_mask])
        featured_df.loc[buy_mask, "tp_price"] = close[buy_mask] + (self.atr_multiplier_tp * atr[buy_mask])

        sell_mask = featured_df["signal"] == -1
        featured_df.loc[sell_mask, "sl_price"] = close[sell_mask] + (self.atr_multiplier_sl * atr[sell_mask])
        featured_df.loc[sell_mask, "tp_price"] = close[sell_mask] - (self.atr_multiplier_tp * atr[sell_mask])

        return featured_df

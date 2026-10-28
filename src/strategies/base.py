"""Base Strategy Interface."""

from abc import ABC, abstractmethod
import pandas as pd


class BaseStrategy(ABC):
    """Abstract Base Class for all quantitative and AI strategies."""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Processes historical or live candle DataFrame and returns DataFrame with:
        - 'signal': 1 (BUY), -1 (SELL), 0 (HOLD)
        - 'sl_price': suggested stop-loss price
        - 'tp_price': suggested take-profit price
        """
        pass

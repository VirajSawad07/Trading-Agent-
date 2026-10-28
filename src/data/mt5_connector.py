"""MetaTrader 5 (MT5) Data Connector and Offline Synthetic Data Generator."""

import os
from datetime import datetime
from typing import Dict, Optional
import numpy as np
import pandas as pd

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False


TIMEFRAME_MAP = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 16385,
    "H4": 16388,
    "D1": 16408,
}


class MT5Connector:
    def __init__(
        self,
        login: Optional[int] = None,
        password: Optional[str] = None,
        server: Optional[str] = None,
        path: Optional[str] = None,
    ):
        self.login = login
        self.password = password
        self.server = server
        self.path = path
        self.connected = False

    def is_terminal_running(self) -> bool:
        """Checks if terminal64.exe is running in Windows process table."""
        try:
            import subprocess
            out = subprocess.check_output('tasklist /fi "imagename eq terminal64.exe"', shell=True, text=True)
            return "terminal64.exe" in out.lower()
        except Exception:
            return False

    def connect(self) -> bool:
        """Initializes connection to MT5 desktop terminal."""
        if not MT5_AVAILABLE:
            print("[MT5Connector] Warning: MetaTrader5 python package not available.")
            return False

        # Fast-path check: If terminal is not running and no path is specified, skip IPC hang
        if not self.path and not self.is_terminal_running():
            print("[MT5Connector] MT5 Terminal (terminal64.exe) is not currently running.")
            return False

        init_args = {"timeout": 3000}
        if self.path:
            init_args["path"] = self.path
        if self.login and self.password and self.server:
            init_args["login"] = int(self.login)
            init_args["password"] = self.password
            init_args["server"] = self.server

        if mt5.initialize(**init_args):
            self.connected = True
            terminal_info = mt5.terminal_info()
            print(f"[MT5Connector] Successfully connected to MT5 Terminal: {terminal_info.name if terminal_info else 'Unknown'}")
            return True
        else:
            err = mt5.last_error()
            print(f"[MT5Connector] MT5 Terminal initialize failed: {err}")
            return False

    def disconnect(self):
        """Shutdown MT5 terminal connection."""
        if MT5_AVAILABLE and self.connected:
            mt5.shutdown()
            self.connected = False

    def get_symbol_specs(self, symbol: str = "XAUUSD") -> Dict:
        """Retrieves live broker specification for the symbol."""
        if not self.connected:
            return {
                "symbol": symbol,
                "contract_size": 100.0,
                "point": 0.01,
                "digits": 2,
                "spread": 25,
                "volume_min": 0.01,
                "volume_max": 2.0,
                "volume_step": 0.01,
            }

        info = mt5.symbol_info(symbol)
        if info is None:
            print(f"[MT5Connector] Symbol {symbol} not found in Market Watch.")
            return {}

        return {
            "symbol": symbol,
            "contract_size": info.trade_contract_size,
            "point": info.point,
            "digits": info.digits,
            "spread": info.spread,
            "volume_min": info.volume_min,
            "volume_max": info.volume_max,
            "volume_step": info.volume_step,
        }

    def fetch_historical_bars(
        self,
        symbol: str = "XAUUSD",
        timeframe_str: str = "M15",
        bars_count: int = 5000,
    ) -> pd.DataFrame:
        """Downloads historical OHLCV bars from MT5."""
        if not self.connected:
            raise ConnectionError("MT5 is not connected. Call connect() first or use generate_sample_gold_data().")

        tf = TIMEFRAME_MAP.get(timeframe_str, 15)
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, bars_count)

        if rates is None or len(rates) == 0:
            err = mt5.last_error()
            raise RuntimeError(f"Failed to copy rates for {symbol} ({timeframe_str}): {err}")

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df = df.set_index("time")
        df = df.rename(columns={"tick_volume": "volume"})
        return df[["open", "high", "low", "close", "volume"]]

    @staticmethod
    def generate_sample_gold_data(
        bars_count: int = 5000,
        start_price: float = 2650.0,
        freq: str = "15min",
    ) -> pd.DataFrame:
        """Generates realistic gold price series (Geometric Brownian Motion + session volatility).
        
        Used for local development, CI tests, and backtesting when MT5 is offline.
        """
        np.random.seed(42)
        end_time = datetime.now()
        dates = pd.date_range(end=end_time, periods=bars_count, freq=freq)

        # Baseline return noise
        dt = 1.0 / (252 * 24 * 4)  # 15m delta
        volatility = 0.16          # 16% annualized volatility for Gold
        mu = 0.05                  # 5% annual drift

        returns = np.random.normal(
            loc=(mu - 0.5 * volatility**2) * dt,
            scale=volatility * np.sqrt(dt),
            size=bars_count,
        )

        # Session multiplier: higher volatility during London & NY sessions
        hours = dates.hour
        session_scale = np.where((hours >= 12) & (hours <= 16), 1.6, 1.0)
        returns = returns * session_scale

        price_series = start_price * np.exp(np.cumsum(returns))

        # Create OHLC candles around the price series
        noise = np.random.uniform(0.5, 2.5, size=bars_count)
        opens = price_series + np.random.normal(0, 0.2, size=bars_count)
        closes = price_series + np.random.normal(0, 0.2, size=bars_count)
        highs = np.maximum(opens, closes) + noise
        lows = np.minimum(opens, closes) - noise
        volumes = np.random.randint(100, 3000, size=bars_count)

        df = pd.DataFrame(
            {
                "open": np.round(opens, 2),
                "high": np.round(highs, 2),
                "low": np.round(lows, 2),
                "close": np.round(closes, 2),
                "volume": volumes,
            },
            index=dates,
        )
        df.index.name = "time"
        return df

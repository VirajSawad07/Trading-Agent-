"""Download multi-year OHLC history from the running MT5 terminal.

Unlike src/download_data.py this never falls back to synthetic data: no MT5, no file.
It only reads prices, so it runs on demo and real accounts alike. On brokers listed in
config/broker_symbols.yaml it reads the broker's name (e.g. XAUUSDs) and saves the file
under the bots' name (XAUUSD), so the bots find it.

    python -m src.data.fetch_history --symbols XAUUSD EURUSD --timeframes H1 H4 --start 2021-01-01
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

TIMEFRAMES = ["M15", "M30", "H1", "H4", "D1"]


def main():
    import MetaTrader5 as mt5

    parser = argparse.ArgumentParser(description="Download MT5 price history (read-only; any account).")
    parser.add_argument("--symbols", nargs="+", default=["XAUUSD", "EURUSD"])
    parser.add_argument("--timeframes", nargs="+", default=["H1", "H4"], choices=TIMEFRAMES)
    parser.add_argument("--start", default="2021-01-01")
    parser.add_argument("--out", default="data/raw")
    parser.add_argument("--tag", default="", help="suffix for the file name, e.g. _2009")
    args = parser.parse_args()

    if not mt5.initialize():
        sys.exit(f"[Data] MT5 initialize failed: {mt5.last_error()}")
    from src.live.signals import broker_symbol
    server = mt5.account_info().server

    start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    end = datetime.now(timezone.utc)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    for sym in args.symbols:
        name = broker_symbol(sym, server)
        mt5.symbol_select(name, True)
        for tf_name in args.timeframes:
            # One request per year: long ranges exceed the terminal's per-call limit.
            chunks = []
            for year in range(start.year, end.year + 1):
                lo = max(start, datetime(year, 1, 1, tzinfo=timezone.utc))
                hi = min(end, datetime(year + 1, 1, 1, tzinfo=timezone.utc))
                rates = mt5.copy_rates_range(name, getattr(mt5, f"TIMEFRAME_{tf_name}"), lo, hi)
                if rates is not None and len(rates):
                    chunks.append(pd.DataFrame(rates))
            if not chunks:
                print(f"[Data] {sym} {tf_name}: no data ({mt5.last_error()})")
                continue
            # Drop the last bar: it is still forming and its prices will change.
            df = pd.concat(chunks).drop_duplicates("time").sort_values("time").iloc[:-1]
            # Times are broker server time (MetaQuotes-Demo: UTC+2 winter / UTC+3 summer).
            df["time"] = pd.to_datetime(df["time"], unit="s")
            df = df.rename(columns={"tick_volume": "volume"})[["time", "open", "high", "low", "close", "volume", "spread"]]
            path = out / f"{sym}_{tf_name}_mt5{args.tag}.csv"
            df.to_csv(path, index=False)
            print(f"[Data] {sym} {tf_name}: {len(df)} bars {df.time.iloc[0]} -> {df.time.iloc[-1]} -> {path}")

    mt5.shutdown()


if __name__ == "__main__":
    main()

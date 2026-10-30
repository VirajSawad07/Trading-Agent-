"""Data Download & Ingestion CLI Script."""

import argparse
import os
import yaml
from dotenv import load_dotenv
from src.data.mt5_connector import MT5Connector


def main():
    parser = argparse.ArgumentParser(description="Download Gold historical data from MT5 or generate sample dataset.")
    parser.add_argument("--symbol", type=str, default="XAUUSD", help="Symbol name (e.g., XAUUSD, GOLD)")
    parser.add_argument("--timeframe", type=str, default="M15", help="Timeframe (e.g., M5, M15, H1)")
    parser.add_argument("--bars", type=int, default=10000, help="Number of bars to fetch")
    parser.add_argument("--force-sample", action="store_true", help="Force synthetic sample generation without MT5")
    args = parser.parse_args()

    load_dotenv()
    with open("config/config.yaml", "r") as f:
        config = yaml.safe_load(f)

    raw_dir = config.get("paths", {}).get("raw_data_dir", "data/raw")
    os.makedirs(raw_dir, exist_ok=True)
    out_filename = f"{args.symbol}_{args.timeframe}.csv"
    out_path = os.path.join(raw_dir, out_filename)

    df = None
    if not args.force_sample:
        connector = MT5Connector(
            login=os.getenv("MT5_LOGIN"),
            password=os.getenv("MT5_PASSWORD"),
            server=os.getenv("MT5_SERVER"),
            path=os.getenv("MT5_PATH"),
        )
        if connector.connect():
            try:
                print(f"[Data] Requesting {args.bars} bars of {args.symbol} ({args.timeframe}) from MT5...")
                df = connector.fetch_historical_bars(symbol=args.symbol, timeframe_str=args.timeframe, bars_count=args.bars)
                print(f"[Data] Successfully retrieved {len(df)} live bars from broker MT5!")
            except Exception as e:
                print(f"[Data] MT5 fetch encountered an error: {e}")
            finally:
                connector.disconnect()

    if df is None and not args.force_sample:
        # Never fall back silently: fake prices once produced a meaningless Sharpe of 11.
        raise SystemExit("[Data] Could not get bars from MT5, so nothing was written. "
                         "Open MT5 and retry, or pass --force-sample for clearly labelled fake data.")
    if df is None:
        print(f"[Data] Generating SYNTHETIC {args.symbol} {args.timeframe} dataset ({args.bars} bars). Not real prices.")
        df = MT5Connector.generate_sample_gold_data(bars_count=args.bars, freq="15min")
        out_path = os.path.join(raw_dir, f"{args.symbol}_{args.timeframe}_SYNTHETIC.csv")

    df.to_csv(out_path)
    print(f"[Data] Saved dataset to {out_path}")


if __name__ == "__main__":
    main()

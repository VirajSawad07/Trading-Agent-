# Running the paper trader

Demo account only. The gateway refuses any other account type.

## Start

1. Open MT5, log in to the demo account, and turn on Algo Trading.
2. Start the bot and leave its window open:

   ```bash
   .venv/Scripts/python -m src.live.paper_trader --sizing-equity 100000 --risk-pct 0.005
   ```

3. Optional, in a second window. Read-only, at http://127.0.0.1:8050:

   ```bash
   .venv/Scripts/python -m src.live.dashboard
   ```

## What stops it

The bot does not restart itself. A reboot, sleep, closed window or closed MT5 stops it.
Open trades keep their stop and target at the broker, but time exits and reversals wait
until the bot is back. Run the start command again to resume; it will not resend an
order it already placed. Hours missed while it was off are not decided afterwards.

## Check on it

```bash
.venv/Scripts/python -m src.live.ledger summary reports/live/ledger_XAUUSD_H1.jsonl
.venv/Scripts/python -m src.live.ledger verify reports/live/ledger_XAUUSD_H1.jsonl
```

## Reading the results

Compare average R per trade with the backtest's +0.105 R. Expect about 16 trades a year,
so a few weeks of data will not settle anything. The backtest edge itself is unproven.

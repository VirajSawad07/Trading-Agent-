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

## Autostart at login

The scheduled task `TradingBot-PaperTrader` runs `scripts/start_bot.ps1` hidden when you
log in. It opens MT5, starts the dashboard, and starts the trader sized as a $1,000 account (gold at the 0.01 minimum lot, `config/risk_limits_1k.yaml`),
restarting it within a minute if it exits. It never restarts after the trader refuses a
non-demo account. Its log is `reports/live/logs/autostart.log`.

```powershell
Stop-ScheduledTask -TaskName TradingBot-PaperTrader        # stop it now
Disable-ScheduledTask -TaskName TradingBot-PaperTrader     # no autostart
Unregister-ScheduledTask -TaskName TradingBot-PaperTrader  # remove it
```

Stopping the task may leave the Python processes running; end them in Task Manager.

## MT5 watchdog

MT5 sometimes stops answering the bot ("IPC timeout") for hours while still open. If MT5
has been unreachable for 10 minutes, the bot closes and reopens it, at most once every
30 minutes. Open trades are unaffected: their stop and target are held by the broker.
The ledger records each outage once (`error`), each restart (`watchdog`) and the recovery
(`reconnected`).

## What stops it

A shutdown or sleep still stops the bot; it resumes at your next login. Open trades keep
their stop and target at the broker, but time exits and reversals wait until the bot is
back. It will not resend an order it already placed. Hours missed while it was off are
not decided afterwards.

## Check on it

```bash
.venv/Scripts/python -m src.live.ledger summary reports/live/ledger_XAUUSD_H1.jsonl
.venv/Scripts/python -m src.live.ledger verify reports/live/ledger_XAUUSD_H1.jsonl
```

## Reading the results

Compare average R per trade with the backtest's +0.105 R. Expect about 16 trades a year,
so a few weeks of data will not settle anything. The backtest edge itself is unproven.

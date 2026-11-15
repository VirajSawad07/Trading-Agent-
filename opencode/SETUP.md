# Setting up the bots on a new laptop

Windows only: the `MetaTrader5` Python package needs the Windows MT5 terminal.

## 1. Before you start

- **Make sure no other laptop is running the bots on the same MT5 account.** Two copies on
  one account can open the same trade twice. (The Nepal laptop was stopped on 2026-11-16.)
- Install **MetaTrader 5** from the broker, log in, and turn on **Algo Trading** (toolbar).
- Install **Python 3.13** and **git**.

## 2. Get the code and install

```bash
git clone https://github.com/VirajSawad07/Trading-Agent-.git
cd Trading-Agent-
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m pytest -q
```

All tests should pass (75 at hand-over). `.env` is not in the repo; only the old
`src/live_trader.py` path needs it, and the two bots below do not.

## 3. Broker market names

The bots use names like `XAUUSD` and `US500`. Brokers often add a suffix. Check the server
name in MT5 (File > Login, or the account panel), then make sure
`config/broker_symbols.yaml` has an entry for it. `SwitchMarkets-Live` is already there:

```yaml
SwitchMarkets-Live:
  XAUUSD: XAUUSDs
  US500: US500s
  ...
```

For another broker, add a block with that server's exact name and the broker's symbol for
each market (find them in MT5's Market Watch). A server not listed uses the plain names.

## 4. Download price history (the gold bot needs it)

The gold bot trains its model on hourly gold history from 2009. Prices are only read, so
this works on demo and real accounts:

```bash
.venv/Scripts/python -m src.data.fetch_history --symbols XAUUSD --timeframes H1 --start 2009-01-01 --tag _2009
.venv/Scripts/python -m src.data.fetch_history --symbols US500 US30 USTEC DE40 AUS200 FRA40 EUSTX50 --timeframes D1 --start 2012-01-01
```

The first creates `data/raw/XAUUSD_H1_mt5_2009.csv`. A broker that keeps less history
gives a shorter file; the bot still runs. The second is only for the dip bot's replay check.

## 5. Start the bots

Each in its own terminal, or use the autostart in step 6.

```bash
.venv/Scripts/python -m src.live.paper_trader --sizing-equity 1000 --risk-config config/risk_limits_1k.yaml
.venv/Scripts/python -m src.live.dip_trader
.venv/Scripts/python -m src.live.dashboard
```

- **Demo account:** both bots trade the demo.
- **Real account:** both refuse to trade. Add `--signals-only` to run them in signals-only
  mode: they read the real account's prices and log every decision, but place no orders.

## 6. Autostart at login (optional)

`scripts/start_bot.ps1` opens MT5, starts the dashboard and both bots, restarts them if
they exit, and switches them to signals-only on a real account (back to trading on demo).
Register it once in PowerShell, from the repo folder:

```powershell
$root = (Get-Location).Path
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$root\scripts\start_bot.ps1`"" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable
Register-ScheduledTask -TaskName "TradingBot-PaperTrader" -Action $action -Trigger $trigger -Settings $settings
Start-ScheduledTask -TaskName "TradingBot-PaperTrader"
```

`scripts/start_bot.ps1` expects MT5 at `C:\Program Files\MetaTrader 5\terminal64.exe`.
A broker's own MT5 build often installs elsewhere; change `$terminal` at the top of the
script if so. Stop with `Stop-ScheduledTask -TaskName TradingBot-PaperTrader`, and turn off
autostart with `Disable-ScheduledTask -TaskName TradingBot-PaperTrader`.

## 7. Check on it

- Dashboard: http://127.0.0.1:8050 (account, one tab per market, every decision, logs).
- Ledgers: `.venv/Scripts/python -m src.live.ledger summary reports/live/ledger_XAUUSD_H1.jsonl`
  and `... verify ...` for each ledger.
- Logs: `reports/live/logs/` (`paper_XAUUSD_H1*.log`, `dips_D1*.log`, `autostart*.log`).
- Dip bot rule check: `.venv/Scripts/python -m src.live.dip_trader check` (after step 4).

Expect long quiet spells: gold about 16 trades a year, index dips about 3 a month. Most
checks end in "No trade". Markets are closed at weekends; the dashboard shows when each
reopens.

## Sharing results

Commit the ledgers and push, so both laptops see the same record:

```bash
git add reports/live/ledger_*.jsonl
git commit -m "Update ledgers"
git push
```

Only the laptop that runs the bots should commit ledgers, or the two copies will conflict.

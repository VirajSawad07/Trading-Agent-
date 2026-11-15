# Starts MT5, the dashboard and the paper trader, and restarts the trader if it exits.
# Run at login by the "TradingBot-PaperTrader" scheduled task (see docs/PAPER_TRADING.md).
# Stop it with:  Stop-ScheduledTask -TaskName TradingBot-PaperTrader

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
$terminal = "C:\Program Files\MetaTrader 5\terminal64.exe"
$logDir = Join-Path $root "reports\live\logs"
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir "autostart.log"
$LIVE_ACCOUNT_EXIT = 3  # matches src/live/paper_trader.py

function Say($msg) { Add-Content -Path $log -Value "$(Get-Date -Format s) $msg" }

# One copy only: a second trader on the same account would fight the first.
$mutex = New-Object System.Threading.Mutex($false, "Global\TradingBotPaperTrader")
if (-not $mutex.WaitOne(0)) { Say "Already running; this copy exits."; exit 0 }

Say "Autostart begins."
if (-not (Get-Process terminal64 -ErrorAction SilentlyContinue)) {
    Start-Process $terminal
    Say "Started MT5; waiting for it to log in."
    Start-Sleep -Seconds 60
}

if (-not (Get-NetTCPConnection -LocalPort 8050 -State Listen -ErrorAction SilentlyContinue)) {
    Start-Process $py -ArgumentList "-m", "src.live.dashboard" -WorkingDirectory $root -WindowStyle Hidden
    Say "Started dashboard on http://127.0.0.1:8050."
}

# Index dip demo trial (docs/RESEARCH_PLAN.md, Revision 1 Step B): its own restart loop.
Start-Process powershell.exe -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
    "-File", "`"$(Join-Path $PSScriptRoot 'start_dips.ps1')`"" -WorkingDirectory $root -WindowStyle Hidden  # quoted: the path has a space
Say "Started the dip trader loop."

# Demo account: the bot trades the demo. Real account: it runs signals-only (logs every
# decision, orders disabled) and switches back when MT5 is on demo again.
$SIGNALS_DEMO_EXIT = 4
$signals = $false
while ($true) {
    $args_ = @("-m", "src.live.paper_trader", "--sizing-equity", "1000", "--risk-config", "config/risk_limits_1k.yaml")
    if ($signals) { $args_ += "--signals-only" }
    Say "Starting gold bot ($(if ($signals) { 'signals only, real account' } else { 'demo trading' }))."
    # The trader writes its own log (paper_XAUUSD_H1*.log); stderr is kept for startup crashes.
    $p = Start-Process $py -ArgumentList $args_ -WorkingDirectory $root -NoNewWindow -Wait -PassThru `
        -RedirectStandardError (Join-Path $logDir "autostart_trader.err")
    $code = $p.ExitCode
    if ($code -eq $LIVE_ACCOUNT_EXIT) {
        Say "MT5 is on a non-demo account: switching to signals only (no orders)."
        $signals = $true
        continue
    }
    if ($code -eq $SIGNALS_DEMO_EXIT) {
        Say "MT5 is on a demo account again: switching back to demo trading."
        $signals = $false
        continue
    }
    Say "Trader exited with code $code; restarting in 60 s."
    Start-Sleep -Seconds 60
}

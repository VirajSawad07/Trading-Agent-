# Keeps the index dip demo trader (src/live/dip_trader.py) running; restarts it if it exits.
# Started hidden by scripts/start_bot.ps1 at login. MT5 is opened, and restarted when frozen,
# by the gold bot; this script only waits for it.

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
$logDir = Join-Path $root "reports\live\logs"
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir "autostart_dips.log"
$LIVE_ACCOUNT_EXIT = 3  # matches src/live/paper_trader.py

function Say($msg) { Add-Content -Path $log -Value "$(Get-Date -Format s) $msg" }

$mutex = New-Object System.Threading.Mutex($false, "Global\TradingBotDipTrader")
if (-not $mutex.WaitOne(0)) { Say "Already running; this copy exits."; exit 0 }

Start-Sleep -Seconds 90  # let MT5 open and log in first
while ($true) {
    Say "Starting dip trader."
    $p = Start-Process $py -ArgumentList "-m", "src.live.dip_trader" -WorkingDirectory $root -NoNewWindow -Wait -PassThru `
        -RedirectStandardError (Join-Path $logDir "autostart_dips.err")
    $code = $p.ExitCode
    if ($code -eq $LIVE_ACCOUNT_EXIT) {
        Say "Dip trader refused a non-demo account (exit $code). Not restarting."
        break
    }
    Say "Dip trader exited with code $code; restarting in 60 s."
    Start-Sleep -Seconds 60
}

# devboard-start.ps1 — поднимает Flask-дашборд (Windows PowerShell).
#
# Использование:
#   powershell -ExecutionPolicy Bypass -File commands\devboard-start.ps1
#
# По смыслу — то же что devboard-start.sh на Unix.

$ErrorActionPreference = "Stop"

$REPO_ROOT = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DATA_DIR = Join-Path $REPO_ROOT "data"
$DASH_DIR = Join-Path $REPO_ROOT "dashboard"
$LOG_FILE = Join-Path $DATA_DIR "dashboard.log"
$PID_FILE = Join-Path $DATA_DIR "dashboard.pid"

New-Item -ItemType Directory -Force -Path $DATA_DIR | Out-Null

$DashPython = Join-Path $DASH_DIR ".venv\Scripts\python.exe"
$McpPython  = Join-Path $REPO_ROOT "mcp_server\.venv\Scripts\python.exe"

if (-not (Test-Path $DashPython) -or -not (Test-Path $McpPython)) {
    Write-Host "venv не настроен. Запустите сначала: python setup.py" -ForegroundColor Yellow
    exit 1
}

# Если уже работает — не перезапускать
if (Test-Path $PID_FILE) {
    $oldPid = Get-Content $PID_FILE
    $proc = Get-Process -Id $oldPid -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "Дашборд уже работает (pid=$oldPid). http://127.0.0.1:5000"
        exit 0
    }
    Remove-Item $PID_FILE -Force
}

$env:PRIDE_TASKS_DB = if ($env:PRIDE_TASKS_DB) { $env:PRIDE_TASKS_DB } else { Join-Path $DATA_DIR "tasks.db" }
$env:PRIDE_DASHBOARD_PORT = if ($env:PRIDE_DASHBOARD_PORT) { $env:PRIDE_DASHBOARD_PORT } else { "4999" }
$env:PRIDE_DASHBOARD_HOST = if ($env:PRIDE_DASHBOARD_HOST) { $env:PRIDE_DASHBOARD_HOST } else { "127.0.0.1" }

Push-Location $DASH_DIR
$proc = Start-Process -FilePath $DashPython -ArgumentList "app.py" `
    -RedirectStandardOutput $LOG_FILE -RedirectStandardError $LOG_FILE `
    -WindowStyle Hidden -PassThru
Pop-Location

Set-Content -Path $PID_FILE -Value $proc.Id
Start-Sleep -Seconds 1

if (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue) {
    Write-Host "✓ Дашборд запущен (pid=$($proc.Id)). http://$($env:PRIDE_DASHBOARD_HOST):$($env:PRIDE_DASHBOARD_PORT)" -ForegroundColor Green
    Write-Host "  Логи: $LOG_FILE"
    Write-Host "  Стоп: powershell -ExecutionPolicy Bypass -File commands\devboard-stop.ps1"
} else {
    Write-Host "✗ Не удалось запустить. См. $LOG_FILE" -ForegroundColor Red
    Remove-Item $PID_FILE -Force -ErrorAction SilentlyContinue
    exit 1
}

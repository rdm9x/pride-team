# devboard-stop.ps1 — останавливает дашборд и сессию тимлида (Windows).

$ErrorActionPreference = "Continue"

$REPO_ROOT = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DATA_DIR = Join-Path $REPO_ROOT "data"

function Stop-Pid([string]$File, [string]$Label) {
    if (-not (Test-Path $File)) {
        Write-Host "$Label не запущен"
        return
    }
    $procPid = Get-Content $File
    $proc = Get-Process -Id $procPid -ErrorAction SilentlyContinue
    if ($proc) {
        Stop-Process -Id $procPid -Force
        Start-Sleep -Milliseconds 500
        Write-Host "✓ $Label остановлен (pid=$procPid)" -ForegroundColor Green
    } else {
        Write-Host "$Label не работал (stale pid=$procPid)"
    }
    Remove-Item $File -Force -ErrorAction SilentlyContinue
}

Stop-Pid (Join-Path $DATA_DIR "team.pid")      "Тимлид"
Stop-Pid (Join-Path $DATA_DIR "dashboard.pid") "Дашборд"

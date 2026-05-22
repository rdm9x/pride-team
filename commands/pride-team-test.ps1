# pride-team-test.ps1 — единый прогон тестов малой команды (Windows).

$ErrorActionPreference = "Continue"

$REPO_ROOT = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ExitCode = 0

Write-Host "=== mcp_server/tests ==="
$McpPytest = Join-Path $REPO_ROOT "mcp_server\.venv\Scripts\pytest.exe"
if (-not (Test-Path $McpPytest)) {
    Write-Host "venv не настроен. Запустите: python setup.py" -ForegroundColor Yellow
    exit 1
}
& $McpPytest (Join-Path $REPO_ROOT "mcp_server\tests\")
if ($LASTEXITCODE -ne 0) { $ExitCode = $LASTEXITCODE }

Write-Host ""
Write-Host "=== dashboard/tests ==="
$DashPytest = Join-Path $REPO_ROOT "dashboard\.venv\Scripts\pytest.exe"
& $DashPytest (Join-Path $REPO_ROOT "dashboard\tests\")
if ($LASTEXITCODE -ne 0) { $ExitCode = $LASTEXITCODE }

Write-Host ""
if ($ExitCode -eq 0) {
    Write-Host "✓ Все тесты зелёные." -ForegroundColor Green
} else {
    Write-Host "✗ Есть упавшие тесты (exit=$ExitCode)" -ForegroundColor Red
}
exit $ExitCode

# devboard-work.ps1 — запускает сессию claude как тимлида (Windows).
# Вызывается дашбордом из «▶ Запустить команду».

$ErrorActionPreference = "Stop"

$REPO_ROOT = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ROLE_FILE = Join-Path $REPO_ROOT "roles\тимлид.md"

if (-not (Test-Path $ROLE_FILE)) {
    Write-Error "Не найден файл роли: $ROLE_FILE"
    exit 1
}

$TeamleadPrompt = Get-Content -Path $ROLE_FILE -Raw -Encoding UTF8

$TaskPrompt = @"
Старт сессии тимлида.

1) ЧАТ с пользователем — mcp__pride-tasks__chat_recent(limit=20). Если есть
   сообщения от него без твоего ответа — ответь через
   mcp__pride-tasks__chat_post(author="тимлид", text="...") ДО задач.

2) Канбан: list_tasks(status="todo", assignee="тимлид"), потом wip, потом
   list_tasks(status="needs_approval").

3) Для каждой новой: декомпозируй на 2-6 атомарных подзадач (create_task
   с parent_id, assignee=бэкенд|qa). Subagent'ы — параллельно через Task tool.

4) Собери результаты, ревьюй, обнови статусы.

5) Финал: chat_post(author="тимлид", text="итоги: ...") — короткое резюме
   для пользователя. Какие задачи в review, какие нуждаются в одобрении.
"@

Set-Location $REPO_ROOT

# Авто-роутер моделей: алгоритмический, без LLM.
# Override через env PRIDE_TEAM_MODEL=opus|sonnet|haiku.
if ($env:PRIDE_TEAM_MODEL) {
    $Model = $env:PRIDE_TEAM_MODEL
    Write-Host "🤖 роутер: модель навязана через PRIDE_TEAM_MODEL=$Model"
} else {
    $env:PYTHONPATH = Join-Path $REPO_ROOT "mcp_server"
    $Python = Join-Path $REPO_ROOT "mcp_server\.venv\Scripts\python.exe"
    $Model = (& $Python -m pride_tasks.router model-only)
    $Decision = (& $Python -m pride_tasks.router pick)
    Write-Host "🤖 роутер: $Model"
    Write-Host $Decision
}
$McpConfig = Join-Path $REPO_ROOT ".mcp.json"

& claude `
    --append-system-prompt $TeamleadPrompt `
    --permission-mode bypassPermissions `
    --model $Model `
    --mcp-config $McpConfig `
    --output-format stream-json `
    --verbose `
    --include-partial-messages `
    --print $TaskPrompt

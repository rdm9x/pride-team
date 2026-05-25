# devboard-work.ps1 — запускает сессию claude как тимлида (Windows).
# Вызывается дашбордом из «▶ Запустить команду».

$ErrorActionPreference = "Stop"

# UTF-8 для всего вывода (без этого кириллица в иероглифы)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding  = [System.Text.Encoding]::UTF8
$OutputEncoding           = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING     = "utf-8"
$env:PYTHONUTF8           = "1"
try { chcp 65001 > $null } catch {}

$REPO_ROOT = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

# === Парсинг --role <slug> ===
# Backward compat: если --role не передан, default = dev-lead (тимлид dev-отдела).
$RoleSlug = "dev-lead"
for ($i = 0; $i -lt $args.Count; $i++) {
    if ($args[$i] -eq "--role" -and ($i + 1) -lt $args.Count) {
        $RoleSlug = $args[$i + 1]
        $i++
    }
}

# === Поиск файла роли ===
# Если слаг содержит '/' — прямой путь: roles\<slug>.md
# Иначе ищем по порядку:
#   1. roles\<slug>.md
#   2. roles\dev\<slug>.md
#   3. roles\marketing\<slug>.md
#   4. Паттерн <dept>-<role>: roles\<dept>\<role>.md (например dev-lead → roles\dev\lead.md)
$RoleSlugPath = $RoleSlug.Replace("/", "\")
if ($RoleSlug -match "/") {
    $ROLE_FILE = Join-Path $REPO_ROOT "roles\$RoleSlugPath.md"
} elseif (Test-Path (Join-Path $REPO_ROOT "roles\$RoleSlug.md")) {
    $ROLE_FILE = Join-Path $REPO_ROOT "roles\$RoleSlug.md"
} elseif (Test-Path (Join-Path $REPO_ROOT "roles\dev\$RoleSlug.md")) {
    $ROLE_FILE = Join-Path $REPO_ROOT "roles\dev\$RoleSlug.md"
} elseif (Test-Path (Join-Path $REPO_ROOT "roles\marketing\$RoleSlug.md")) {
    $ROLE_FILE = Join-Path $REPO_ROOT "roles\marketing\$RoleSlug.md"
} elseif ($RoleSlug -match "^([^-]+)-(.+)$") {
    # Паттерн <dept>-<role> → roles\<dept>\<role>.md
    $DeptPart = $Matches[1]
    $RolePart = $Matches[2]
    $CandidateFile = Join-Path $REPO_ROOT "roles\$DeptPart\$RolePart.md"
    if (Test-Path $CandidateFile) {
        $ROLE_FILE = $CandidateFile
    } else {
        $ROLE_FILE = Join-Path $REPO_ROOT "roles\$RoleSlug.md"
    }
} else {
    $ROLE_FILE = Join-Path $REPO_ROOT "roles\$RoleSlug.md"
}

if (-not (Test-Path $ROLE_FILE)) {
    Write-Error "Не найден файл роли: $ROLE_FILE (slug='$RoleSlug')"
    exit 1
}

$TeamleadPrompt = Get-Content -Path $ROLE_FILE -Raw -Encoding UTF8

$TaskPrompt = @"
Старт сессии тимлида.

1) ЧАТ с пользователем — mcp__pride-tasks__chat_recent(limit=20). Если есть
   сообщения от него без твоего ответа — ответь через
   mcp__pride-tasks__chat_post(author="$RoleSlug", text="...") ДО задач.

2) Канбан: list_tasks(status="todo", assignee="$RoleSlug"), потом wip, потом
   list_tasks(status="needs_approval").

3) Для каждой новой: декомпозируй на 2-6 атомарных подзадач (create_task
   с parent_id, assignee=бэкенд|qa). Subagent'ы — параллельно через Task tool.

4) Собери результаты, ревьюй, обнови статусы.

5) Финал: chat_post(author="$RoleSlug", text="итоги: ...") — короткое резюме
   для пользователя. Какие задачи в review, какие нуждаются в одобрении.
"@

Set-Location $REPO_ROOT

# ADR-006 (S15.2): Prompt caching — экономит ~40-50% токенов на prefix (роль + AGENTS.md).
# TTL кэша: 5 минут (ephemeral). Cache read стоит 10% от обычной цены input.
$env:ANTHROPIC_PROMPT_CACHING_ENABLED = "1"

# === Output locale (S2.2) ===
$OutputLocale = "ru"
$LocaleFile = Join-Path $REPO_ROOT "data\.output_locale"
if (Test-Path $LocaleFile) {
    $OutputLocale = (Get-Content $LocaleFile -Raw).Trim()
}

# === User expertise (S3.4) ===
$env:DEVBOARD_USER_EXPERTISE = "non-tech"
$ExpertiseFile = Join-Path $REPO_ROOT "data\.user_expertise"
if (Test-Path $ExpertiseFile) {
    $env:DEVBOARD_USER_EXPERTISE = (Get-Content $ExpertiseFile -Raw).Trim()
}

# === Language prompt ===
if ($OutputLocale -eq "en") {
    $LangPrompt = "OUTPUT LANGUAGE: Reply in English. This applies to: chat messages, task titles/descriptions/comments you write, all conversational text. Code, file paths, identifiers remain in their original form."
} else {
    $LangPrompt = "OUTPUT LANGUAGE: Отвечай на русском языке. Это касается: сообщений в чат, названий задач, описаний, комментариев. Код, пути файлов, идентификаторы оставляй как есть."
}

# === Авто-роутер моделей: алгоритмический, без LLM. ===
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

# === Non-tech user profile prompt (S3.4) ===
if ($env:DEVBOARD_USER_EXPERTISE -eq "non-tech") {
    $ExpertisePrompt = @'
USER PROFILE: non-technical

Write in plain language:
- Explain technical terms on first mention in parentheses.
- For user actions — step by step, like for a beginner.
- Avoid abbreviations (CI, MCP, PR, ADR) without explanation.
- If asking user for a decision — offer concrete options, not open questions.
- Before escalating "need your decision" — try to offer a sensible default.

If the user starts using technical terms themselves — switch to technical language.
'@
    & claude `
        --append-system-prompt $TeamleadPrompt `
        --append-system-prompt $LangPrompt `
        --append-system-prompt $ExpertisePrompt `
        --permission-mode bypassPermissions `
        --model $Model `
        --mcp-config $McpConfig `
        --output-format stream-json `
        --verbose `
        --include-partial-messages `
        --print $TaskPrompt
} else {
    & claude `
        --append-system-prompt $TeamleadPrompt `
        --append-system-prompt $LangPrompt `
        --permission-mode bypassPermissions `
        --model $Model `
        --mcp-config $McpConfig `
        --output-format stream-json `
        --verbose `
        --include-partial-messages `
        --print $TaskPrompt
}

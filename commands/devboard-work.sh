#!/usr/bin/env bash
# devboard-work.sh — запускает сессию claude как тимлида.
#
# Дашборд вызывает этот скрипт через subprocess.Popen когда пользователь жмёт
# «Запустить команду». stdout стримится в SSE /api/team/stream.
#
# Используется `claude --print` (non-interactive) с:
#  - системным промтом тимлида (roles/dev/lead.md);
#  - MCP devboard-tasks через .mcp.json в корне devboard;
#  - permission-mode=bypassPermissions (нужно для авто-выполнения tool-ов
#    в headless-режиме без человека-оператора). Approval-gate'ы реализованы
#    НА УРОВНЕ ROLE PROMPTS: тимлид/бэкенд обязаны создавать needs_approval-
#    подзадачи перед критичными операциями, пользователь аппрувит в дашборде.
#  - model=opus (для тимлида нужно длинное окно + хорошее планирование).

set -euo pipefail

# ADR-006 (S15.2): Prompt caching — экономит ~40-50% токенов на prefix (роль + AGENTS.md).
# Раскомментируй строку ниже чтобы включить автоматическое кэширование префикса.
# TTL кэша: 5 минут (ephemeral). Cache read стоит 10% от обычной цены input.
# Подробности: docs/adr/0006-token-optimization.md §2.1
export ANTHROPIC_PROMPT_CACHING_ENABLED=1

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# === Парсинг --role <slug> ===
# Backward compat: если --role не передан, default = dev-lead (тимлид dev-отдела).
ROLE_SLUG="dev-lead"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --role)
            ROLE_SLUG="${2:-}"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

# === Поиск файла роли ===
# Если слаг содержит '/' — прямой путь: roles/<slug>.md
# Иначе ищем по порядку:
#   1. roles/<slug>.md
#   2. roles/dev/<slug>.md
#   3. roles/marketing/<slug>.md
#   4. Паттерн <dept>-<role>: roles/<dept>/<role>.md (например dev-lead → roles/dev/lead.md)
if [[ "$ROLE_SLUG" == *"/"* ]]; then
    ROLE_FILE="$REPO_ROOT/roles/${ROLE_SLUG}.md"
else
    if [[ -f "$REPO_ROOT/roles/${ROLE_SLUG}.md" ]]; then
        ROLE_FILE="$REPO_ROOT/roles/${ROLE_SLUG}.md"
    elif [[ -f "$REPO_ROOT/roles/dev/${ROLE_SLUG}.md" ]]; then
        ROLE_FILE="$REPO_ROOT/roles/dev/${ROLE_SLUG}.md"
    elif [[ -f "$REPO_ROOT/roles/marketing/${ROLE_SLUG}.md" ]]; then
        ROLE_FILE="$REPO_ROOT/roles/marketing/${ROLE_SLUG}.md"
    elif [[ "$ROLE_SLUG" == *"-"* ]]; then
        # Паттерн <dept>-<role> → roles/<dept>/<role>.md
        _DEPT="${ROLE_SLUG%%-*}"
        _ROLE="${ROLE_SLUG#*-}"
        if [[ -f "$REPO_ROOT/roles/${_DEPT}/${_ROLE}.md" ]]; then
            ROLE_FILE="$REPO_ROOT/roles/${_DEPT}/${_ROLE}.md"
        else
            ROLE_FILE="$REPO_ROOT/roles/${ROLE_SLUG}.md"
        fi
    else
        ROLE_FILE="$REPO_ROOT/roles/${ROLE_SLUG}.md"
    fi
fi

if [[ ! -f "$ROLE_FILE" ]]; then
    echo "Не найден файл роли: $ROLE_FILE (slug='$ROLE_SLUG')" >&2
    exit 1
fi

TEAMLEAD_PROMPT="$(cat "$ROLE_FILE")"

TASK_PROMPT="Старт сессии тимлида.

1) ЧАТ с пользователем — mcp__devboard-tasks__chat_recent(limit=20). Если есть
   сообщения от него без твоего ответа — ответь через
   mcp__devboard-tasks__chat_post(author=\"${ROLE_SLUG}\", text=\"...\") ДО задач.

2) Канбан: list_tasks(status=\"todo\", assignee=\"${ROLE_SLUG}\"), потом wip, потом
   list_tasks(status=\"needs_approval\").

3) Для каждой новой: декомпозируй на 2-6 атомарных подзадач (create_task
   с parent_id, assignee=бэкенд|qa). Subagent'ы — параллельно через Task tool
   (subagent_type=general-purpose, prompt = roles/бэкенд.md или roles/qa.md
   + описание подзадачи + id).

4) Собери результаты, ревьюй, обнови статусы родительских задач.

5) Финал: chat_post(author=\"${ROLE_SLUG}\", text=\"итоги: ...\") — короткое резюме
   для пользователя. Какие задачи в review, какие нуждаются в одобрении."

cd "$REPO_ROOT"

# === Output locale ===
# Читаем output locale (записывается dashboard/app.py из localStorage фронта)
OUTPUT_LOCALE="ru"
if [ -f "$REPO_ROOT/data/.output_locale" ]; then
    OUTPUT_LOCALE=$(cat "$REPO_ROOT/data/.output_locale" | tr -d '[:space:]')
fi

# === User expertise (S3.4) ===
# Читаем профиль пользователя, записанный dashboard/app.py при POST /api/team/start
DEVBOARD_USER_EXPERTISE="non-tech"
if [ -f "$REPO_ROOT/data/.user_expertise" ]; then
    DEVBOARD_USER_EXPERTISE=$(cat "$REPO_ROOT/data/.user_expertise" | tr -d '[:space:]')
fi
export DEVBOARD_USER_EXPERTISE

# Формируем append-system-prompt для языка вывода
if [ "$OUTPUT_LOCALE" = "en" ]; then
    LANG_PROMPT="OUTPUT LANGUAGE: Reply in English. This applies to: chat messages, task titles/descriptions/comments you write, all conversational text. Code, file paths, identifiers remain in their original form."
else
    LANG_PROMPT="OUTPUT LANGUAGE: Отвечай на русском языке. Это касается: сообщений в чат, названий задач, описаний, комментариев. Код, пути файлов, идентификаторы оставляй как есть."
fi

# === Авто-роутер моделей ===
# Перед стартом тимлида решаем какую модель использовать на этой сессии.
# Алгоритмический (без LLM, без расходов). Подробности — в router.py.
# Override: DEVBOARD_TEAM_MODEL=opus|sonnet|haiku force-выбор.
if [[ -n "${DEVBOARD_TEAM_MODEL:-}" ]]; then
    MODEL_ALIAS="$DEVBOARD_TEAM_MODEL"
    echo "🤖 роутер: модель навязана через DEVBOARD_TEAM_MODEL=$MODEL_ALIAS"
else
    MODEL_ALIAS=$(
      PYTHONPATH="$REPO_ROOT/mcp_server" \
      "$REPO_ROOT/mcp_server/.venv/bin/python" \
      -m devboard_tasks.router model-only
    )
    DECISION=$(
      PYTHONPATH="$REPO_ROOT/mcp_server" \
      "$REPO_ROOT/mcp_server/.venv/bin/python" \
      -m devboard_tasks.router pick
    )
    echo "🤖 роутер: $MODEL_ALIAS"
    echo "$DECISION"
fi

# === Non-tech user profile prompt ===
# Если пользователь не технический — добавляем инструкции упрощённого языка.
if [ "$DEVBOARD_USER_EXPERTISE" = "non-tech" ]; then
    EXPERTISE_PROMPT='USER PROFILE: non-technical

Write in plain language:
- Explain technical terms on first mention in parentheses.
- For user actions — step by step, like for a beginner.
- Avoid abbreviations (CI, MCP, PR, ADR) without explanation.
- If asking user for a decision — offer concrete options, not open questions.
- Before escalating "need your decision" — try to offer a sensible default.

If the user starts using technical terms themselves — switch to technical language.'

    exec claude \
        --append-system-prompt "$TEAMLEAD_PROMPT" \
        --append-system-prompt "$LANG_PROMPT" \
        --append-system-prompt "$EXPERTISE_PROMPT" \
        --permission-mode bypassPermissions \
        --model "$MODEL_ALIAS" \
        --mcp-config "$REPO_ROOT/.mcp.json" \
        --output-format stream-json \
        --verbose \
        --include-partial-messages \
        --print "$TASK_PROMPT"
else
    exec claude \
        --append-system-prompt "$TEAMLEAD_PROMPT" \
        --append-system-prompt "$LANG_PROMPT" \
        --permission-mode bypassPermissions \
        --model "$MODEL_ALIAS" \
        --mcp-config "$REPO_ROOT/.mcp.json" \
        --output-format stream-json \
        --verbose \
        --include-partial-messages \
        --print "$TASK_PROMPT"
fi

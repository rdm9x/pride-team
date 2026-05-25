#!/usr/bin/env bash
# devboard-managing.sh — запускает сессию claude как Управляющего (Managing Director).
#
# Аналог devboard-work.sh, но использует roles/управляющий.md как системный промт
# вместо roles/dev/lead.md.
#
# Дашборд вызывает этот скрипт через subprocess.Popen когда role='managing-director'.
# stdout стримится в SSE /api/team/stream.
#
# Используется `claude --print` (non-interactive) с:
#  - системным промтом Управляющего (roles/управляющий.md);
#  - MCP devboard-tasks через .mcp.json в корне devboard;
#  - permission-mode=bypassPermissions (нужно для авто-выполнения tool-ов
#    в headless-режиме без человека-оператора). Approval-gate'ы реализованы
#    НА УРОВНЕ ROLE PROMPTS: Управляющий обязан создавать needs_approval-
#    подзадачи перед критичными операциями, пользователь аппрувит в дашборде.

set -euo pipefail

# ADR-006 (S15.2): Prompt caching
export ANTHROPIC_PROMPT_CACHING_ENABLED=1

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ ! -f "$REPO_ROOT/roles/управляющий.md" ]]; then
    echo "Не найден roles/управляющий.md в $REPO_ROOT" >&2
    exit 1
fi

MANAGING_PROMPT="$(cat "$REPO_ROOT/roles/управляющий.md")"

TASK_PROMPT='Старт сессии Управляющего.

1) ЧАТ с пользователем — mcp__devboard-tasks__chat_recent(limit=20). Если есть
   сообщения от него без твоего ответа — ответь через
   mcp__devboard-tasks__chat_post(author="управляющий", text="...") ДО задач.

2) Долгосрочная память — manager_memory_recent(limit=10). Сверься с контекстом
   предыдущих сессий.

3) Канбан: list_tasks(status="todo", assignee="управляющий"), потом wip, потом
   list_tasks(status="needs_approval").

4) Для каждой новой задачи: декомпозируй на подзадачи и делегируй лидам
   соответствующих отделов (create_task с parent_id, assignee=лид-отдела).

5) Финал: chat_post(author="управляющий", text="итоги: ...") — краткое резюме
   для пользователя. Какие задачи делегированы, какие в review, какие ждут одобрения.'

cd "$REPO_ROOT"

# === Output locale ===
OUTPUT_LOCALE="ru"
if [ -f "$REPO_ROOT/data/.output_locale" ]; then
    OUTPUT_LOCALE=$(cat "$REPO_ROOT/data/.output_locale" | tr -d '[:space:]')
fi

# === User expertise (S3.4) ===
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
        --append-system-prompt "$MANAGING_PROMPT" \
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
        --append-system-prompt "$MANAGING_PROMPT" \
        --append-system-prompt "$LANG_PROMPT" \
        --permission-mode bypassPermissions \
        --model "$MODEL_ALIAS" \
        --mcp-config "$REPO_ROOT/.mcp.json" \
        --output-format stream-json \
        --verbose \
        --include-partial-messages \
        --print "$TASK_PROMPT"
fi

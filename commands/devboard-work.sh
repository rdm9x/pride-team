#!/usr/bin/env bash
# devboard-work.sh — запускает сессию claude как тимлида.
#
# Дашборд вызывает этот скрипт через subprocess.Popen когда Дмитрий жмёт
# «Запустить команду». stdout стримится в SSE /api/team/stream.
#
# Используется `claude --print` (non-interactive) с:
#  - системным промтом тимлида (roles/тимлид.md);
#  - MCP pride-tasks через .mcp.json в /D.AI/команда/;
#  - permission-mode=bypassPermissions (нужно для авто-выполнения tool-ов
#    в headless-режиме без человека-оператора). Approval-gate'ы реализованы
#    НА УРОВНЕ ROLE PROMPTS: тимлид/бэкенд обязаны создавать needs_approval-
#    подзадачи перед критичными операциями, Дмитрий аппрувит в дашборде.
#  - model=opus (для тимлида нужно длинное окно + хорошее планирование).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ ! -f "$REPO_ROOT/roles/тимлид.md" ]]; then
    echo "Не найден roles/тимлид.md в $REPO_ROOT" >&2
    exit 1
fi

TEAMLEAD_PROMPT="$(cat "$REPO_ROOT/roles/тимлид.md")"

TASK_PROMPT='Старт сессии тимлида.

1) ЧАТ с Дмитрием — mcp__pride-tasks__chat_recent(limit=20). Если есть
   сообщения от него без твоего ответа — ответь через
   mcp__pride-tasks__chat_post(author="тимлид", text="...") ДО задач.

2) Канбан: list_tasks(status="todo", assignee="тимлид"), потом wip, потом
   list_tasks(status="needs_approval").

3) Для каждой новой: декомпозируй на 2-6 атомарных подзадач (create_task
   с parent_id, assignee=бэкенд|qa). Subagent'\''ы — параллельно через Task tool
   (subagent_type=general-purpose, prompt = roles/бэкенд.md или roles/qa.md
   + описание подзадачи + id).

4) Собери результаты, ревьюй, обнови статусы родительских задач.

5) Финал: chat_post(author="тимлид", text="итоги: ...") — короткое резюме
   для Дмитрия. Какие задачи в review, какие нуждаются в одобрении.'

cd "$REPO_ROOT"

# === Авто-роутер моделей ===
# Перед стартом тимлида решаем какую модель использовать на этой сессии.
# Алгоритмический (без LLM, без расходов). Подробности — в router.py.
# Override: PRIDE_TEAM_MODEL=opus|sonnet|haiku force-выбор.
if [[ -n "${PRIDE_TEAM_MODEL:-}" ]]; then
    MODEL_ALIAS="$PRIDE_TEAM_MODEL"
    echo "🤖 роутер: модель навязана через PRIDE_TEAM_MODEL=$MODEL_ALIAS"
else
    MODEL_ALIAS=$(
      PYTHONPATH="$REPO_ROOT/mcp_server" \
      "$REPO_ROOT/mcp_server/.venv/bin/python" \
      -m pride_tasks.router model-only
    )
    DECISION=$(
      PYTHONPATH="$REPO_ROOT/mcp_server" \
      "$REPO_ROOT/mcp_server/.venv/bin/python" \
      -m pride_tasks.router pick
    )
    echo "🤖 роутер: $MODEL_ALIAS"
    echo "$DECISION"
fi

exec claude \
    --append-system-prompt "$TEAMLEAD_PROMPT" \
    --permission-mode bypassPermissions \
    --model "$MODEL_ALIAS" \
    --mcp-config "$REPO_ROOT/.mcp.json" \
    --output-format stream-json \
    --verbose \
    --include-partial-messages \
    --print "$TASK_PROMPT"

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
#   0. spec: managing-director → roles/управляющий.md (русское имя файла)
#   1. roles/<slug>.md
#   2. roles/dev/<slug>.md
#   3. roles/marketing/<slug>.md
#   4. Паттерн <dept>-<role>: roles/<dept>/<role>.md (например dev-lead → roles/dev/lead.md)
if [[ "$ROLE_SLUG" == "managing-director" ]]; then
    ROLE_FILE="$REPO_ROOT/roles/управляющий.md"
elif [[ "$ROLE_SLUG" == *"/"* ]]; then
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

# --- Planning mode (Phase 3b) -------------------------------------------------
# Если оркестратор запустил лида внутри планёрки, он передаёт:
#   DEVBOARD_PLANNING_MODE=1
#   DEVBOARD_PLANNING_ID=<session_id>
#   DEVBOARD_THREAD_ID=<thread_id>
#   DEVBOARD_PLANNING_ROUND=<n>
# Для лидов отделов — даём реплику в общем треде.
# Для managing-director — финальный синтез отчёта.
if [[ "${DEVBOARD_PLANNING_MODE:-0}" == "1" && "${ROLE_SLUG}" == "managing-director" ]]; then
    PLANNING_ID="${DEVBOARD_PLANNING_ID:-}"
    THREAD_ID="${DEVBOARD_THREAD_ID:-}"
    TASK_PROMPT="Финальный синтез планёрки (planning_session_id=${PLANNING_ID}).

Ты — Управляющий. Раунды лидов закончены, твоя задача — собрать итог.

1) Прочитай thread по REST:
       curl http://127.0.0.1:4999/api/threads/${THREAD_ID}/messages
   В нём: системное сообщение с темой планёрки + реплики лидов отделов
   по раундам. Цитировать не надо, нужен СИНТЕЗ.

2) Напиши финальный отчёт в формате:

   ## Решение по планёрке #${PLANNING_ID:0:6}

   **Что предлагаем:**
   - <предлагаемый шаг 1, конкретно>
   - <шаг 2>
   - <шаг 3>

   **Кому что делать:**
   - <отдел A>: <короткая роль>
   - <отдел B>: <короткая роль>

   **Открытые вопросы для owner-а** (если есть):
   - <вопрос>

   **Риски** (если есть):
   - <риск + mitigation>

3) Запости отчёт в thread:
       curl -X POST http://127.0.0.1:4999/api/threads/${THREAD_ID}/messages \\
            -H 'Content-Type: application/json' \\
            -d '{\"author\":\"managing-director\",\"text\":\"<отчёт>\"}'

4) Заверши сессию. Никаких задач не создавай — owner сначала apprve отчёт.

ЗАПРЕТЫ: НЕ создавать задачи (это после accept), НЕ дёргать subagent'ов,
НЕ обновлять канбан."
elif [[ "${DEVBOARD_PLANNING_MODE:-0}" == "1" ]]; then
    PLANNING_ID="${DEVBOARD_PLANNING_ID:-}"
    THREAD_ID="${DEVBOARD_THREAD_ID:-}"
    PLANNING_ROUND="${DEVBOARD_PLANNING_ROUND:-1}"
    TASK_PROMPT="Ты участвуешь в ПЛАНЁРКЕ как ${ROLE_SLUG}. Это НЕ обычная сессия —
канбан НЕ трогай, новые задачи НЕ создавай, специалистов НЕ запускай.

Контекст:
- planning_session_id: ${PLANNING_ID}
- thread_id: ${THREAD_ID}
- текущий раунд: ${PLANNING_ROUND}

Что делать (один проход, не цикл):

1) Прочитай thread через MCP-инструмент:
   mcp__devboard-tasks__chat_recent читает legacy-чат, поэтому используй
   get_thread_messages напрямую через прямой sqlite — нельзя. Вместо этого
   читай через REST:
       curl http://127.0.0.1:4999/api/threads/${THREAD_ID}/messages
   и разбери последние ~20 сообщений. Тема планёрки в системном сообщении
   от managing-director (начинается с «🤔 Планёрка #...»).

2) Подумай с позиции своей роли (${ROLE_SLUG}):
   - Раунд 1: твой первый взгляд — какие подходы / решения / риски ты видишь
     с точки зрения своего отдела. Конкретно, без воды, 3-5 предложений.
   - Раунд 2+: ты УЖЕ видишь реплики других лидов. Реагируй на них:
     согласись / возрази / предложи объединить подходы. Не повторяй своё
     прошлое — двигай обсуждение вперёд.

3) Напиши ОДНУ реплику в thread через REST POST:
       curl -X POST http://127.0.0.1:4999/api/threads/${THREAD_ID}/messages \\
            -H 'Content-Type: application/json' \\
            -d '{\"author\":\"${ROLE_SLUG}\",\"text\":\"<твой текст>\"}'

   Реплика должна быть КОНКРЕТНОЙ и КОРОТКОЙ (5-12 строк, можно с маркерами).
   Никаких «жду указаний» / «готов начать работу» — это планёрка, твоё мнение нужно.

4) Заверши сессию. Больше ничего не делай — оркестратор позовёт лида следующего
   отдела или начнёт новый раунд.

ЗАПРЕТЫ:
- НЕ создавать задачи через MCP.
- НЕ запускать subagent'ов.
- НЕ постить в department-chat (это для обычной работы).
- НЕ писать длинные эссе — это диалог, не отчёт."
else
    TASK_PROMPT="Старт сессии тимлида (${ROLE_SLUG}).

1) ЧАТ с пользователем — mcp__devboard-tasks__chat_recent(limit=20). Если есть
   сообщения от него без твоего ответа — ответь через
   mcp__devboard-tasks__chat_post(author=\"${ROLE_SLUG}\", text=\"...\") ДО задач.

2) КАНБАН — ты КООРДИНАТОР отдела. Дочерние задачи assigned на специалистов
   (бэкенд/qa/frontend/devops/архитектор/техписатель), а ТЫ их делегируешь
   через Task tool. НЕ жди сигнала от owner-а — это твоя работа.

   Шаги:
   a) mcp__devboard-tasks__list_tasks(status='todo', limit=50) — ВСЕ todo.
   b) Отфильтруй задачи где department_id='dev' (или твой отдел) ИЛИ
      assignee in (бэкенд, qa, архитектор, frontend, devops, техписатель).
   c) Также list_tasks(status='wip', assignee='${ROLE_SLUG}') — что было начато.
   d) Также list_tasks(status='needs_approval', assignee='${ROLE_SLUG}').

3) Для каждой todo задачи специалиста (НЕ parent-эпиков с label=epic):
   a) **СНАЧАЛА** mcp__devboard-tasks__update_task(id, status='wip') — переводим
      в работу ДО делегирования. Owner должен видеть прогресс в колонке «В работе».
      Если этого не сделать — задачи будут мигать todo→review минуя wip,
      и owner не поймёт что реально делается прямо сейчас.
   b) Запусти subagent через Task tool параллельно (до 4-5 одновременно
      в одном сообщении): subagent_type=general-purpose, prompt = содержимое
      файла roles/<assignee>.md + description задачи + id задачи.
   c) Subagent НЕ имеет MCP — после его завершения ТЫ сам делаешь
      mcp__devboard-tasks__update_task(id, status='review').

   Parent-эпики (label=epic с уже декомпозированными children) — НЕ трогай.
   Работай напрямую с child задачами.

4) Параллельность важна: 4-5 subagent'ов сразу в одном сообщении (несколько tool_use).
   **Перед** делегированием — батч из update_task(status='wip') для всех 4-5 одновременно.
   После сбора результатов — батч update_task(status='review').
   Owner таким образом видит реальный pipeline: wip → subagent работает → review.

5) Финал: ОБЯЗАТЕЛЬНО chat_post(author=\"${ROLE_SLUG}\",
   text=\"итоги: делегировал N задач, M в review\") — короткое резюме.

ЗАПРЕТЫ:
- НЕ пиши 'жду твоего сигнала какую роль запустить' — owner ставит задачи,
  ты их выполняешь автономно без подтверждения.
- НЕ запускай app.py для проверки UI — dashboard работает на :4999 отдельно.
- НЕ используй timeout (нет на macOS).
- Сигнал owner-а нужен ТОЛЬКО для acceptance review→done."
fi

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

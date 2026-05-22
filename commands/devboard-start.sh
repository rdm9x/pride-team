#!/usr/bin/env bash
# devboard-start.sh — поднимает Flask-дашборд малой команды.
#
# MCP-сервер pride-tasks НЕ запускается как отдельный демон — он stdio-сервер
# и стартует автоматически когда тимлид (claude -p) подключается через
# .mcp.json. Дашборд работает с теми же tools через прямой Python-импорт.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="$REPO_ROOT/data"
DASH_DIR="$REPO_ROOT/dashboard"
LOG_FILE="$DATA_DIR/dashboard.log"
PID_FILE="$DATA_DIR/dashboard.pid"

mkdir -p "$DATA_DIR"

# Проверка venv
if [[ ! -x "$DASH_DIR/.venv/bin/python" ]]; then
    echo "venv дашборда не найден. Создаю через uv…"
    (cd "$DASH_DIR" && uv venv && uv pip install -e .)
fi
if [[ ! -x "$REPO_ROOT/mcp_server/.venv/bin/python" ]]; then
    echo "venv MCP-сервера не найден. Создаю через uv…"
    (cd "$REPO_ROOT/mcp_server" && uv venv && uv pip install -e ".[dev]")
fi

# Если уже запущен — не перезапускаем
if [[ -f "$PID_FILE" ]]; then
    OLD_PID="$(cat "$PID_FILE")"
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Дашборд уже работает (pid=$OLD_PID). http://127.0.0.1:5000"
        exit 0
    fi
    rm -f "$PID_FILE"
fi

export PRIDE_TASKS_DB="${PRIDE_TASKS_DB:-$DATA_DIR/tasks.db}"
# Порт 5000 на macOS Sonoma+ занят AirPlay Receiver → используем 4999.
export PRIDE_DASHBOARD_PORT="${PRIDE_DASHBOARD_PORT:-4999}"
export PRIDE_DASHBOARD_HOST="${PRIDE_DASHBOARD_HOST:-127.0.0.1}"

cd "$DASH_DIR"
nohup "$DASH_DIR/.venv/bin/python" app.py >> "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"
sleep 1
PID="$(cat "$PID_FILE")"

if kill -0 "$PID" 2>/dev/null; then
    echo "✓ Дашборд запущен (pid=$PID). http://$PRIDE_DASHBOARD_HOST:$PRIDE_DASHBOARD_PORT"
    echo "  Логи: $LOG_FILE"
    echo "  БД:   $PRIDE_TASKS_DB"
    echo "  Стоп: $REPO_ROOT/commands/devboard-stop.sh"
else
    echo "✗ Не удалось запустить дашборд. См. $LOG_FILE"
    rm -f "$PID_FILE"
    exit 1
fi

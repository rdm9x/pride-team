#!/usr/bin/env bash
# devboard-stop.sh — останавливает дашборд (и live-сессию тимлида если есть).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="$REPO_ROOT/data"
DASH_PID_FILE="$DATA_DIR/dashboard.pid"
TEAM_PID_FILE="$DATA_DIR/team.pid"

stop_pid() {
    local file="$1"
    local label="$2"
    if [[ ! -f "$file" ]]; then
        echo "$label не запущен"
        return 0
    fi
    local pid
    pid="$(cat "$file")"
    if kill -0 "$pid" 2>/dev/null; then
        kill "$pid"
        sleep 1
        if kill -0 "$pid" 2>/dev/null; then
            kill -9 "$pid"
        fi
        echo "✓ $label остановлен (pid=$pid)"
    else
        echo "$label не работал (stale pid=$pid)"
    fi
    rm -f "$file"
}

# Сначала команда (тимлид), потом дашборд (он же управляет тимлидом)
stop_pid "$TEAM_PID_FILE" "Тимлид"
stop_pid "$DASH_PID_FILE" "Дашборд"

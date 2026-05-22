#!/usr/bin/env bash
# Двойной клик в Finder → дашборд pride-team запускается, открывается браузер.
# Окно Terminal остаётся открытым с логами — закроешь его, дашборд остановится.

set -e

# Папка где лежит этот скрипт (учитывает кириллицу/пробелы)
REPO="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO"

clear
cat <<'BANNER'
┌────────────────────────────────────────────────┐
│           pride-team — запуск                  │
└────────────────────────────────────────────────┘

BANNER

# 1) Python проверка
if ! command -v python3 >/dev/null 2>&1; then
    cat <<'ERR'
✗ Python 3 не найден.

Установи Python 3.11+ с https://www.python.org/downloads/
Не забудь поставить галочку «Add Python to PATH».
После установки запусти этот файл снова.

ERR
    read -p "Нажми Enter чтобы закрыть… " _
    exit 1
fi

PY_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
echo "✓ Python $PY_VER найден"

# 2) Первый запуск — поставить зависимости
if [[ ! -x "$REPO/mcp_server/.venv/bin/python" ]] || [[ ! -x "$REPO/dashboard/.venv/bin/python" ]]; then
    echo ""
    echo "⚙ Первый запуск — устанавливаю зависимости. Займёт 1-2 минуты…"
    echo ""
    python3 setup.py
    if [[ $? -ne 0 ]]; then
        echo ""
        echo "✗ Установка упала. Прокрути выше — найди причину."
        read -p "Enter чтобы закрыть… " _
        exit 1
    fi
fi

# 3) Старт дашборда
PORT="${PRIDE_DASHBOARD_PORT:-4999}"
export PRIDE_DASHBOARD_PORT="$PORT"
echo ""
echo "▶ Запускаю дашборд на порту $PORT…"
bash "$REPO/commands/pride-team-start.sh"

# 4) Ждём пока healthz отвечает 200 (до 20 секунд)
URL="http://127.0.0.1:$PORT"
echo -n "  ждём готовности"
for i in $(seq 1 40); do
    if curl -fs --max-time 1 "$URL/healthz" >/dev/null 2>&1; then
        echo " ✓"
        break
    fi
    echo -n "."
    sleep 0.5
done

# 5) Открываем браузер
open "$URL" 2>/dev/null || true

cat <<INFO

────────────────────────────────────────────────
✓ Дашборд работает: $URL

  • Не закрывай это окно — иначе дашборд остановится.
  • Чтобы остановить — нажми Ctrl+C ниже либо закрой окно.
  • Логи: data/dashboard.log
────────────────────────────────────────────────

INFO

# Держим окно открытым и следим за дашбордом
PID_FILE="$REPO/data/dashboard.pid"
if [[ -f "$PID_FILE" ]]; then
    PID=$(cat "$PID_FILE")
    # Ловим Ctrl+C и корректно останавливаем
    trap 'echo ""; echo "Останавливаю дашборд…"; bash "$REPO/commands/pride-team-stop.sh"; exit 0' INT TERM
    # Ждём пока процесс жив
    while kill -0 "$PID" 2>/dev/null; do
        sleep 2
    done
    echo "(дашборд завершился сам)"
fi
read -p "Enter чтобы закрыть окно… " _

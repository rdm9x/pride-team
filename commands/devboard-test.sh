#!/usr/bin/env bash
# devboard-test.sh — единый прогон всех тестов малой команды.
#
# Запускает pytest в двух венвах подряд (mcp_server + dashboard) и возвращает
# ненулевой exit-code если упал хоть один.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

EXIT_CODE=0

echo "=== mcp_server/tests ==="
if [[ ! -x "$REPO_ROOT/mcp_server/.venv/bin/pytest" ]]; then
    echo "venv mcp_server не найден. Запускаю установку…"
    (cd "$REPO_ROOT/mcp_server" && uv venv && uv pip install -e ".[dev]")
fi
"$REPO_ROOT/mcp_server/.venv/bin/pytest" "$REPO_ROOT/mcp_server/tests/" "$@" \
    || EXIT_CODE=$?

echo ""
echo "=== dashboard/tests ==="
if [[ ! -x "$REPO_ROOT/dashboard/.venv/bin/pytest" ]]; then
    echo "venv dashboard не найден. Запускаю установку…"
    (cd "$REPO_ROOT/dashboard" && uv venv && uv pip install -e . && uv pip install pytest)
fi
"$REPO_ROOT/dashboard/.venv/bin/pytest" "$REPO_ROOT/dashboard/tests/" "$@" \
    || EXIT_CODE=$?

if [[ $EXIT_CODE -eq 0 ]]; then
    echo ""
    echo "✓ Все тесты зелёные."
else
    echo ""
    echo "✗ Есть упавшие тесты (exit=$EXIT_CODE)" >&2
fi

exit $EXIT_CODE

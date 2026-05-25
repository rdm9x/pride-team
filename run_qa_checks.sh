#!/usr/bin/env bash
# QA-проверка Phase 1.8 — полный аудит и тестирование.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "========================================="
echo "🔍 QA-проверка Phase 1.8: Rename pride → devboard"
echo "========================================="
echo ""

# 1. Audit на старые ссылки
echo "1️⃣ Аудит на старые ссылки (pride_tasks, pride-tasks, PRIDE_)..."
cd "$REPO_ROOT"
python3 audit_pride_refs.py
AUDIT_RESULT=$?
echo ""

# 2. Запуск тестов MCP
echo "2️⃣ Запуск тестов MCP-сервера..."
cd "$REPO_ROOT/mcp_server"
if [[ ! -x ".venv/bin/pytest" ]]; then
    echo "   Создаю venv для MCP..."
    uv venv --allow-existing
    uv pip install -e ".[dev]"
fi
.venv/bin/pytest tests/ -v --tb=short 2>&1 | tee /tmp/mcp_tests.log
MCP_TESTS_RESULT=${PIPESTATUS[0]}
echo ""

# 3. Запуск тестов Dashboard
echo "3️⃣ Запуск тестов дашборда..."
cd "$REPO_ROOT/dashboard"
if [[ ! -x ".venv/bin/pytest" ]]; then
    echo "   Создаю venv для дашборда..."
    uv venv --allow-existing
    uv pip install -e .
    uv pip install pytest
fi
.venv/bin/pytest tests/ -v --tb=short 2>&1 | tee /tmp/dashboard_tests.log
DASHBOARD_TESTS_RESULT=${PIPESTATUS[0]}
echo ""

# 4. Coverage
echo "4️⃣ Анализ покрытия..."
cd "$REPO_ROOT/mcp_server"
.venv/bin/pip install coverage -q
.venv/bin/coverage run -m pytest tests/ -q 2>/dev/null || true
echo "   MCP-сервер:"
.venv/bin/coverage report --include="devboard_tasks/**" 2>/dev/null || echo "   (БЕЗ покрытия по путю)"
echo ""

# 5. Проверка дашборда запуска
echo "5️⃣ Проверка базовой конфигурации дашборда..."
cd "$REPO_ROOT/dashboard"
python3 -c "from app import create_app; app = create_app(); print('   ✓ app.create_app работает')" 2>/dev/null || echo "   ✗ Ошибка импорта app"
echo ""

# Итого
echo "========================================="
echo "📋 ИТОГИ:"
echo "========================================="
echo "  Аудит старых ссылок: $([ $AUDIT_RESULT -eq 0 ] && echo '✓ PASS' || echo '✗ FAIL')"
echo "  Тесты MCP: $([ $MCP_TESTS_RESULT -eq 0 ] && echo '✓ PASS' || echo '✗ FAIL')"
echo "  Тесты дашборда: $([ $DASHBOARD_TESTS_RESULT -eq 0 ] && echo '✓ PASS' || echo '✗ FAIL')"
echo ""

if [[ $AUDIT_RESULT -eq 0 && $MCP_TESTS_RESULT -eq 0 && $DASHBOARD_TESTS_RESULT -eq 0 ]]; then
    echo "✓ ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ"
    exit 0
else
    echo "✗ ЕСТЬ ОШИБКИ"
    exit 1
fi

"""Фикстуры для top-level тестов."""

from __future__ import annotations

import sys
from pathlib import Path

# Добавляем mcp_server в sys.path чтобы импортировать devboard_tasks
_MCP_DIR = Path(__file__).resolve().parents[1] / "mcp_server"
if str(_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_MCP_DIR))

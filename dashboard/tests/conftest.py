"""Фикстуры тестов дашборда."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Добавляем родителя в sys.path чтобы импортировать app.py
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Добавляем mcp_server в sys.path чтобы импортировать devboard_tasks
_MCP_DIR = Path(__file__).resolve().parents[2] / "mcp_server"
if str(_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_MCP_DIR))


@pytest.fixture()
def client(tmp_path: Path):
    from app import create_app  # type: ignore

    db = tmp_path / "tasks.db"
    app = create_app(db_path=db)
    app.config["TESTING"] = True
    app.config["DEVBOARD_TASKS_DB"] = str(db)
    return app.test_client()

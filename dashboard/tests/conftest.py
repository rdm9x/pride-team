"""Фикстуры тестов дашборда."""

from __future__ import annotations

import os
import subprocess
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

    # Запускаем миграции для Phase 3a (chat_threads)
    repo_root = Path(__file__).resolve().parents[2]
    app.config["REPO_ROOT"] = str(repo_root)
    migrate_b1_script = repo_root / "scripts" / "migrate_chat_threads.py"
    migrate_b2_script = repo_root / "scripts" / "migrate_chat_threads_b2.py"

    env = os.environ.copy()
    env["DEVBOARD_TASKS_DB"] = str(db)

    if migrate_b1_script.exists():
        subprocess.run([sys.executable, str(migrate_b1_script)], env=env, capture_output=True)

    if migrate_b2_script.exists():
        subprocess.run([sys.executable, str(migrate_b2_script)], env=env, capture_output=True)

    return app.test_client()

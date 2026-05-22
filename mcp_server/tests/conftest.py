"""Общие фикстуры тестов pride-tasks."""

from __future__ import annotations

from pathlib import Path

import pytest

from pride_tasks import db


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    """Чистая БД для каждого теста. Изоляция через PRIDE_TASKS_DB → tmp_path."""

    path = tmp_path / "tasks.db"
    db.init_db(path)
    return path

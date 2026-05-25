"""Тесты F2.1: колонка enabled, PATCH endpoint, сессионный фильтр, MCP list_tasks."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from devboard_tasks import db


# ============================================================
# 1. SQL: колонка существует и DEFAULT=1 для новых задач
# ============================================================


def test_enabled_column_exists_after_init(tmp_path: Path) -> None:
    """После init_db таблица tasks содержит колонку enabled."""
    path = tmp_path / "tasks.db"
    db.init_db(path)
    conn = sqlite3.connect(path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
    finally:
        conn.close()
    assert "enabled" in cols, "Колонка enabled должна существовать в таблице tasks"


def test_new_task_enabled_default_true(tmp_path: Path) -> None:
    """Новая задача создаётся с enabled=True (DEFAULT 1)."""
    path = tmp_path / "tasks.db"
    db.init_db(path)
    task = db.insert_task(path, title="тестовая")
    assert task["enabled"] is True, "Новая задача должна иметь enabled=True"


def test_migration_idempotent_on_existing_db(tmp_path: Path) -> None:
    """Повторный вызов init_db на существующей БД не падает."""
    path = tmp_path / "tasks.db"
    db.init_db(path)
    db.init_db(path)  # второй раз — должен быть idempotent
    task = db.insert_task(path, title="idempotent test")
    assert task["enabled"] is True


def test_enabled_migration_on_old_db_without_column(tmp_path: Path) -> None:
    """Миграция добавляет колонку enabled к уже существующей БД без неё.

    Эмулируем «старую» БД: создаём схему вручную без колонки enabled, затем
    вызываем init_db — колонка должна появиться и задачи получить DEFAULT 1.
    """
    path = tmp_path / "old.db"
    # Создаём «старую» таблицу без enabled
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'todo',
          assignee TEXT,
          reporter TEXT,
          priority TEXT NOT NULL DEFAULT 'P2',
          labels TEXT NOT NULL DEFAULT '[]',
          parent_id TEXT,
          requires_approval INTEGER NOT NULL DEFAULT 0,
          created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL,
          due_at INTEGER,
          completed_at INTEGER,
          result TEXT
        )
        """
    )
    # Вставляем запись без enabled
    conn.execute(
        "INSERT INTO tasks (id, title, created_at, updated_at) VALUES ('aabbcc112233', 'старая', 1000, 1000)"
    )
    conn.commit()
    conn.close()

    # Прогоняем init_db — должен добавить колонку через ensure_dev_department
    db.init_db(path)

    conn = sqlite3.connect(path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
        assert "enabled" in cols, "Миграция должна добавить колонку enabled"
        # Существующая запись должна получить DEFAULT 1
        row = conn.execute(
            "SELECT enabled FROM tasks WHERE id = 'aabbcc112233'"
        ).fetchone()
        assert row is not None
        assert row[0] == 1, "Существующая запись должна иметь enabled=1 после миграции"
    finally:
        conn.close()


# ============================================================
# 2. DB CRUD: update_task меняет enabled, get_task возвращает
# ============================================================


def test_update_task_enabled_false(tmp_path: Path) -> None:
    """db.update_task(enabled=False) сохраняет enabled=False."""
    path = tmp_path / "tasks.db"
    db.init_db(path)
    task = db.insert_task(path, title="выключить")
    assert task["enabled"] is True

    updated = db.update_task(path, task["id"], enabled=False)
    assert updated is not None
    assert updated["enabled"] is False


def test_update_task_enabled_toggle(tmp_path: Path) -> None:
    """enabled можно переключать туда-обратно."""
    path = tmp_path / "tasks.db"
    db.init_db(path)
    task = db.insert_task(path, title="toggle")

    off = db.update_task(path, task["id"], enabled=False)
    assert off["enabled"] is False

    on = db.update_task(path, task["id"], enabled=True)
    assert on["enabled"] is True


def test_get_task_returns_enabled(tmp_path: Path) -> None:
    """get_task с with_history=True возвращает поле enabled."""
    path = tmp_path / "tasks.db"
    db.init_db(path)
    task = db.insert_task(path, title="читать enabled")
    db.update_task(path, task["id"], enabled=False)
    fetched = db.get_task(path, task["id"], with_history=True)
    assert fetched is not None
    assert fetched["enabled"] is False


# ============================================================
# 3. Сессионный фильтр: enabled=0 задача не попадает в выборку
# ============================================================


def test_session_pick_skips_disabled_tasks(tmp_path: Path) -> None:
    """_smart_default_role должна игнорировать задачи с enabled=False.

    Симулируем напрямую через db: создаём todo-задачу с assignee=бэкенд,
    отключаем её — список после фильтра enabled должен быть пустым.
    """
    path = tmp_path / "tasks.db"
    db.init_db(path)
    task = db.insert_task(path, title="disabled task", assignee="бэкенд", status="todo")
    db.update_task(path, task["id"], enabled=False)

    # Получаем todo задачи и применяем фильтр enabled — как это делает pick_model_for_role
    role_tasks = db.list_tasks(path, status="todo", assignee="бэкенд", limit=200)
    filtered = [t for t in role_tasks if t.get("enabled", True)]
    assert filtered == [], "Отключённая задача не должна попасть в очередь"


def test_session_pick_includes_enabled_tasks(tmp_path: Path) -> None:
    """enabled=True задачи должны оставаться в очереди после фильтра."""
    path = tmp_path / "tasks.db"
    db.init_db(path)
    t1 = db.insert_task(path, title="active", assignee="бэкенд", status="todo")
    t2 = db.insert_task(path, title="disabled", assignee="бэкенд", status="todo")
    db.update_task(path, t2["id"], enabled=False)

    role_tasks = db.list_tasks(path, status="todo", assignee="бэкенд", limit=200)
    filtered = [t for t in role_tasks if t.get("enabled", True)]
    ids = {t["id"] for t in filtered}
    assert t1["id"] in ids, "Активная задача должна быть в очереди"
    assert t2["id"] not in ids, "Отключённая задача не должна быть в очереди"


# ============================================================
# 4. MCP list_tasks: поле enabled в выводе
# ============================================================


def test_list_tasks_mcp_includes_enabled(tmp_path: Path) -> None:
    """MCP tools.list_tasks возвращает поле enabled для каждой задачи."""
    from devboard_tasks import tools

    path = tmp_path / "tasks.db"
    db.init_db(path)
    db.insert_task(path, title="task with enabled")

    result = tools.list_tasks(db_path=path)
    assert result["статус"] == "ok"
    assert len(result["задачи"]) == 1
    task = result["задачи"][0]
    assert "enabled" in task, "Поле enabled должно присутствовать в выводе list_tasks"
    assert task["enabled"] is True

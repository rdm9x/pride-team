"""Тесты S8.1: таблица departments, ensure_dev_department, миграция."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from devboard_tasks import db
from devboard_tasks.models import DEFAULT_DEPARTMENT_ID


# ---------------------------------------------------------------------------
# Test 1: после init_db есть таблица departments с одним рядом id='dev'
# ---------------------------------------------------------------------------

def test_init_db_creates_departments_table(tmp_path: Path) -> None:
    """После init_db таблица departments существует и содержит ровно одну запись 'dev'."""
    path = tmp_path / "tasks.db"
    db.init_db(path)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        # Таблица существует.
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        assert "departments" in tables, "Таблица departments не создана"

        # Ровно один ряд, id='dev'.
        rows = conn.execute("SELECT * FROM departments").fetchall()
        assert len(rows) == 1, f"Ожидался 1 ряд в departments, получено {len(rows)}"
        assert rows[0]["id"] == DEFAULT_DEPARTMENT_ID
        assert rows[0]["name"] == "Dev"
        assert rows[0]["archived_at"] is None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Test 2: existing tasks без department_id после ensure_dev_department → 'dev'
# ---------------------------------------------------------------------------

def test_ensure_dev_department_backfills_tasks(tmp_path: Path) -> None:
    """5 задач без department_id после ensure_dev_department получают department_id='dev'."""
    path = tmp_path / "tasks.db"
    db.init_db(path)

    # Вставляем 5 задач напрямую через insert_task (они уже получат department_id='dev').
    # Для чистоты теста сбрасываем department_id вручную через SQL, имитируя legacy.
    task_ids = []
    for i in range(5):
        t = db.insert_task(path, title=f"Task {i}", department_id=None)
        task_ids.append(t["id"])

    # Убеждаемся что ни одна задача не имеет department_id (установили NULL).
    conn_raw = sqlite3.connect(path)
    conn_raw.execute("UPDATE tasks SET department_id = NULL WHERE department_id IS NOT NULL")
    conn_raw.commit()
    rows = conn_raw.execute("SELECT department_id FROM tasks").fetchall()
    assert all(r[0] is None for r in rows), "Не все department_id обнулены (pre-condition)"
    conn_raw.close()

    # Запускаем ensure_dev_department.
    conn = db._connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        db.ensure_dev_department(conn)
        conn.execute("COMMIT")
    finally:
        conn.close()

    # Проверяем: все 5 задач теперь имеют department_id='dev'.
    conn_check = sqlite3.connect(path)
    try:
        rows = conn_check.execute("SELECT department_id FROM tasks").fetchall()
        assert len(rows) == 5
        assert all(r[0] == DEFAULT_DEPARTMENT_ID for r in rows), (
            f"Не все задачи получили department_id='dev': {[r[0] for r in rows]}"
        )
    finally:
        conn_check.close()


# ---------------------------------------------------------------------------
# Test 3: HR и пользователь роли остаются department_id=NULL после миграции
# ---------------------------------------------------------------------------

def test_ensure_dev_department_global_roles_stay_null(tmp_path: Path) -> None:
    """Глобальные роли (hr, пользователь, user, owner) остаются department_id=NULL."""
    path = tmp_path / "tasks.db"
    db.init_db(path)

    # Добавим глобальные роли напрямую.
    conn_raw = sqlite3.connect(path)
    for global_role in ("hr", "пользователь", "user", "owner"):
        conn_raw.execute(
            "INSERT OR REPLACE INTO roles (name, description, capabilities) VALUES (?, ?, ?)",
            (global_role, "глобальная роль", "[]"),
        )
    conn_raw.commit()
    conn_raw.close()

    # Сбросим department_id всех ролей в NULL (включая обычные).
    conn_reset = sqlite3.connect(path)
    conn_reset.execute("UPDATE roles SET department_id = NULL")
    conn_reset.commit()
    conn_reset.close()

    # Прогоняем ensure_dev_department.
    conn = db._connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        db.ensure_dev_department(conn)
        conn.execute("COMMIT")
    finally:
        conn.close()

    conn_check = sqlite3.connect(path)
    conn_check.row_factory = sqlite3.Row
    try:
        roles = {r["name"]: r["department_id"] for r in
                 conn_check.execute("SELECT name, department_id FROM roles").fetchall()}

        # Глобальные — NULL.
        for global_role in ("hr", "пользователь", "user", "owner"):
            assert roles[global_role] is None, (
                f"Роль {global_role!r} должна иметь department_id=NULL, получено {roles[global_role]!r}"
            )

        # Обычные роли devboard — 'dev'.
        for normal_role in ("dev-lead", "бэкенд", "qa", "архитектор", "frontend", "devops", "техписатель"):
            assert roles[normal_role] == DEFAULT_DEPARTMENT_ID, (
                f"Роль {normal_role!r} должна иметь department_id='dev', получено {roles[normal_role]!r}"
            )
    finally:
        conn_check.close()


# ---------------------------------------------------------------------------
# Test 4: миграция идемпотентна
# ---------------------------------------------------------------------------

def test_ensure_dev_department_idempotent(tmp_path: Path) -> None:
    """Повторный вызов ensure_dev_department не дублирует данные и не падает."""
    path = tmp_path / "tasks.db"
    db.init_db(path)

    # Создаём несколько задач.
    for i in range(3):
        db.insert_task(path, title=f"Task {i}")

    # Вызываем ensure_dev_department 3 раза подряд.
    for _ in range(3):
        conn = db._connect(path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            db.ensure_dev_department(conn)
            conn.execute("COMMIT")
        finally:
            conn.close()

    # Проверяем: ровно один ряд 'dev' в departments.
    conn_check = sqlite3.connect(path)
    try:
        dept_count = conn_check.execute(
            "SELECT COUNT(*) FROM departments WHERE id = 'dev'"
        ).fetchone()[0]
        assert dept_count == 1, f"Ожидался 1 ряд 'dev', получено {dept_count}"

        # Все задачи имеют department_id='dev'.
        null_count = conn_check.execute(
            "SELECT COUNT(*) FROM tasks WHERE department_id IS NULL"
        ).fetchone()[0]
        assert null_count == 0, f"Найдены задачи без department_id: {null_count}"
    finally:
        conn_check.close()


# ---------------------------------------------------------------------------
# Test 5: новые tasks через insert_task по умолчанию имеют department_id='dev'
# ---------------------------------------------------------------------------

def test_insert_task_default_department_id(tmp_path: Path) -> None:
    """Новые задачи через insert_task по умолчанию имеют department_id='dev'."""
    path = tmp_path / "tasks.db"
    db.init_db(path)

    task = db.insert_task(path, title="Проверка department_id")

    # В возвращённом dict должен быть department_id='dev'.
    assert "department_id" in task, "department_id отсутствует в ответе insert_task"
    assert task["department_id"] == DEFAULT_DEPARTMENT_ID, (
        f"Ожидался department_id='dev', получено {task['department_id']!r}"
    )

    # Дополнительно — проверим прямо в БД.
    conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            "SELECT department_id FROM tasks WHERE id = ?", (task["id"],)
        ).fetchone()
        assert row is not None
        assert row[0] == DEFAULT_DEPARTMENT_ID
    finally:
        conn.close()

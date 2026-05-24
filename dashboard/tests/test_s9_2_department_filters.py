"""Tests for S9.2 — department-aware фильтры в /api/inbox и /api/roles.

См. roles/frontend.md + AGENTS.md. Контракт:
  - /api/inbox?department=<id> — фильтрует все три ветки (approvals/reviews/questions).
  - /api/inbox?department=__all__ — без фильтра.
  - /api/inbox без параметра — default 'dev' (backward compat).
  - /api/roles?department=__all__ — ВСЕ роли (global + per-dept).
  - /api/roles?department=<id> — global роли (department_id IS NULL) + роли этого отдела.
  - В ответе у каждой роли теперь есть поле department_id (может быть None).
"""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

import pytest


@pytest.fixture()
def client_with_db(tmp_path: Path):
    """Аналог фикстуры client, но дополнительно отдаёт db_path."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app import create_app  # type: ignore

    db = tmp_path / "tasks.db"
    app = create_app(db_path=db)
    app.config["TESTING"] = True
    return app.test_client(), db


def _create_dept(db_path: Path, dept_id: str, name: str = "") -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT OR IGNORE INTO departments (id, name, description, icon, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (dept_id, name or dept_id, "", "🗂", int(time.time())),
        )
        conn.commit()
    finally:
        conn.close()


def _set_task_dept(db_path: Path, tid: str, dept_id: str) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "UPDATE tasks SET department_id = ? WHERE id = ?",
            (dept_id, tid),
        )
        conn.commit()
    finally:
        conn.close()


# === /api/inbox?department= ===


def test_inbox_default_dev_filter(client_with_db) -> None:
    """Без ?department= — default 'dev' (backward compat)."""
    client, db = client_with_db
    tid_dev = client.post("/api/tasks", json={
        "title": "dev needs approval",
        "status": "needs_approval",
        "requires_approval": True,
    }).get_json()["задача"]["id"]
    _create_dept(db, "marketing")
    tid_mk = client.post("/api/tasks", json={
        "title": "marketing approval",
        "status": "needs_approval",
        "requires_approval": True,
    }).get_json()["задача"]["id"]
    _set_task_dept(db, tid_mk, "marketing")

    r = client.get("/api/inbox")
    j = r.get_json()
    assert len(j["approvals"]) == 1
    assert j["approvals"][0]["id"] == tid_dev


def test_inbox_department_filter(client_with_db) -> None:
    """?department=marketing — показывает только marketing-задачи."""
    client, db = client_with_db
    _create_dept(db, "marketing")
    tid_mk = client.post("/api/tasks", json={
        "title": "marketing review",
        "status": "review",
    }).get_json()["задача"]["id"]
    _set_task_dept(db, tid_mk, "marketing")
    # dev review — отфильтровывается
    client.post("/api/tasks", json={
        "title": "dev review",
        "status": "review",
    })

    r = client.get("/api/inbox?department=marketing")
    j = r.get_json()
    assert len(j["reviews"]) == 1
    assert j["reviews"][0]["id"] == tid_mk
    assert j["total"] == 1


def test_inbox_all_no_filter(client_with_db) -> None:
    """?department=__all__ — без фильтрации, видны все отделы."""
    client, db = client_with_db
    _create_dept(db, "marketing")
    client.post("/api/tasks", json={
        "title": "dev review", "status": "review",
    })
    tid_mk = client.post("/api/tasks", json={
        "title": "marketing review", "status": "review",
    }).get_json()["задача"]["id"]
    _set_task_dept(db, tid_mk, "marketing")

    r = client.get("/api/inbox?department=__all__")
    j = r.get_json()
    assert len(j["reviews"]) == 2


# === /api/roles?department= ===


def test_roles_all_returns_global_and_per_dept(client_with_db) -> None:
    """?department=__all__ — возвращает все роли с полем department_id."""
    client, db = client_with_db
    r = client.get("/api/roles?department=__all__")
    assert r.status_code == 200
    j = r.get_json()
    assert j["статус"] == "ok"
    roles = j["роли"]
    assert len(roles) > 0
    for role in roles:
        assert "department_id" in role


def test_roles_filter_includes_globals(client_with_db) -> None:
    """?department=marketing — возвращает global (NULL) + marketing-роли."""
    client, db = client_with_db
    _create_dept(db, "marketing")
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "INSERT INTO roles (name, description, capabilities, department_id) "
            "VALUES (?, ?, ?, ?)",
            ("marketing-lead", "lead", "{}", "marketing"),
        )
        conn.execute(
            "INSERT INTO roles (name, description, capabilities, department_id) "
            "VALUES (?, ?, ?, ?)",
            ("globalrole", "g", "{}", None),
        )
        conn.commit()
    finally:
        conn.close()

    r = client.get("/api/roles?department=marketing")
    assert r.status_code == 200
    j = r.get_json()
    names = {role["name"] for role in j["роли"]}
    assert "marketing-lead" in names
    assert "globalrole" in names


def test_roles_filter_excludes_other_dept(client_with_db) -> None:
    """?department=marketing — НЕ возвращает роли другого отдела."""
    client, db = client_with_db
    _create_dept(db, "marketing")
    _create_dept(db, "design")
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "INSERT INTO roles (name, description, capabilities, department_id) "
            "VALUES (?, ?, ?, ?)",
            ("design-lead", "lead", "{}", "design"),
        )
        conn.commit()
    finally:
        conn.close()

    r = client.get("/api/roles?department=marketing")
    j = r.get_json()
    names = {role["name"] for role in j["роли"]}
    assert "design-lead" not in names

"""Тесты B3 (1.5): проверка динамического assignee по dept_id.

Acceptance:
  - marketing inbox → assignee='marketing-lead'
  - dev inbox → assignee='тимлид' (legacy slug через _find_lead_for_department)
  - нет dept / пустой → fallback 'тимлид' (dev)

Запуск: python -m pytest dashboard/tests/test_assignee_fix.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MCP_DIR = _REPO_ROOT / "mcp_server"
_DASHBOARD_DIR = _REPO_ROOT / "dashboard"

for _p in (_MCP_DIR, _DASHBOARD_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from devboard_tasks import db as _db  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_marketing(db_path: Path) -> None:
    """Создаёт отдел marketing и роль marketing-lead в БД."""
    _db.create_department(db_path, dept_id="marketing", name="Marketing")
    conn = _db._connect(db_path)
    try:
        conn.execute(
            """INSERT OR IGNORE INTO roles (name, description, capabilities, department_id)
               VALUES ('marketing-lead', 'Лид маркетинга', '{}', 'marketing')"""
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Unit-тесты _find_lead_for_department
# ---------------------------------------------------------------------------


def test_find_lead_dev_returns_dev_lead(tmp_path: Path) -> None:
    """_find_lead_for_department(db_path, 'dev') возвращает 'dev-lead' (новая версия)."""
    from app import _find_lead_for_department  # type: ignore

    db_path = tmp_path / "tasks.db"
    _db.init_db(db_path)

    result = _find_lead_for_department(db_path, "dev")
    # D38BCDDA9CF9: миграция переименовала тимлид на dev-lead
    assert result == "dev-lead", f"ожидалось 'dev-lead', получено {result!r}"


def test_find_lead_marketing_returns_marketing_lead(tmp_path: Path) -> None:
    """_find_lead_for_department(db_path, 'marketing') возвращает 'marketing-lead'."""
    from app import _find_lead_for_department  # type: ignore

    db_path = tmp_path / "tasks.db"
    _db.init_db(db_path)
    _setup_marketing(db_path)

    result = _find_lead_for_department(db_path, "marketing")
    assert result == "marketing-lead", f"ожидалось 'marketing-lead', получено {result!r}"


def test_find_lead_unknown_dept_returns_none(tmp_path: Path) -> None:
    """_find_lead_for_department(db_path, 'nonexistent') возвращает None."""
    from app import _find_lead_for_department  # type: ignore

    db_path = tmp_path / "tasks.db"
    _db.init_db(db_path)

    result = _find_lead_for_department(db_path, "nonexistent")
    assert result is None


# ---------------------------------------------------------------------------
# Unit-тесты _has_pending_work с dept_id
# ---------------------------------------------------------------------------


def test_has_pending_work_no_dept_fallback(tmp_path: Path, monkeypatch) -> None:
    """_has_pending_work() без dept_id использует 'dev' → проверяет assignee='тимлид'."""
    import app as _app  # type: ignore

    db_path = tmp_path / "tasks.db"
    _db.init_db(db_path)
    monkeypatch.setattr(_app, "DB_PATH", db_path)

    # Без задач → False
    assert _app._has_pending_work() is False

    # Добавляем задачу с assignee='тимлид' (dev fallback)
    _db.insert_task(
        db_path,
        title="Test task dev",
        assignee="тимлид",
        reporter="пользователь",
        status="todo",
        department_id="dev",
    )

    assert _app._has_pending_work() is True


def test_has_pending_work_marketing_inbox(tmp_path: Path, monkeypatch) -> None:
    """_has_pending_work(dept_id='marketing') проверяет assignee='marketing-lead'."""
    import app as _app  # type: ignore

    db_path = tmp_path / "tasks.db"
    _db.init_db(db_path)
    monkeypatch.setattr(_app, "DB_PATH", db_path)
    _setup_marketing(db_path)

    # Без задач → False
    assert _app._has_pending_work(dept_id="marketing") is False

    # Добавляем задачу marketing-lead
    _db.insert_task(
        db_path,
        title="Marketing task",
        assignee="marketing-lead",
        reporter="пользователь",
        status="todo",
        department_id="marketing",
    )

    assert _app._has_pending_work(dept_id="marketing") is True

    # dev очередь при этом пустая
    assert _app._has_pending_work() is False


# ---------------------------------------------------------------------------
# Интеграционные тесты через Flask-клиент: POST /api/demo с X-Department
# ---------------------------------------------------------------------------


def test_demo_endpoint_dev_assignee_is_timlid(client) -> None:
    """POST /api/demo без X-Department → epic assignee='тимлид' (dev dept)."""
    r = client.post("/api/demo")
    assert r.status_code == 201

    tasks_r = client.get("/api/tasks")
    all_tasks = tasks_r.get_json()["задачи"]
    epic = next(t for t in all_tasks if t["title"] == "Build a landing page")
    assert epic["assignee"] == "тимлид", (
        f"ожидался assignee='тимлид' для dev dept, получено {epic['assignee']!r}"
    )


def test_demo_endpoint_marketing_assignee_is_marketing_lead(client) -> None:
    """POST /api/demo с X-Department: marketing → epic assignee='marketing-lead'."""
    # Создаём marketing-отдел и роль marketing-lead в тестовой БД
    app = client.application
    db_path = Path(app.config["DB_PATH"])
    _setup_marketing(db_path)

    r = client.post("/api/demo", headers={"X-Department": "marketing"})
    assert r.status_code == 201

    tasks_r = client.get("/api/tasks?department=__all__")
    all_tasks = tasks_r.get_json()["задачи"]
    epic = next(
        (t for t in all_tasks if t["title"] == "Build a landing page"), None
    )
    assert epic is not None, "Epic 'Build a landing page' не найден"
    assert epic["assignee"] == "marketing-lead", (
        f"ожидался assignee='marketing-lead', получено {epic['assignee']!r}"
    )

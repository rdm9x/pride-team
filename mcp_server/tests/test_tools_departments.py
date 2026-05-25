"""Тесты S8.2: department_id в MCP-tools, новые tools list/get/create_department."""

from __future__ import annotations

from pathlib import Path

import pytest

from devboard_tasks import db, tools


# ---------------------------------------------------------------------------
# Test 1: list_departments() возвращает отдел 'dev' + counts
# ---------------------------------------------------------------------------

def test_list_departments_returns_dev(db_path: Path) -> None:
    """list_departments() содержит отдел dev после init_db."""
    res = tools.list_departments(db_path=db_path)
    assert res["статус"] == "ok"
    assert res["всего"] >= 1
    dept_ids = [d["id"] for d in res["отделы"]]
    assert "dev" in dept_ids, f"Отдел 'dev' не найден: {dept_ids}"


def test_list_departments_counts(db_path: Path) -> None:
    """list_departments() возвращает корректные counts для dev."""
    # Создаём 2 открытые задачи и 1 в done
    tools.create_task("open-1", db_path=db_path)
    tools.create_task("open-2", db_path=db_path)
    t3 = tools.create_task("done-1", db_path=db_path)
    tools.update_task(t3["задача"]["id"], status="done", _bypass_safety_net=True, db_path=db_path)

    res = tools.list_departments(db_path=db_path)
    assert res["статус"] == "ok"
    dev = next(d for d in res["отделы"] if d["id"] == "dev")
    assert dev["tasks_open"] == 2, f"Ожидалось 2 открытых, получено {dev['tasks_open']}"
    assert dev["tasks_total"] == 3, f"Ожидалось 3 всего, получено {dev['tasks_total']}"


# ---------------------------------------------------------------------------
# Test 2: create_task() без department_id → создаёт в 'dev'
# ---------------------------------------------------------------------------

def test_create_task_default_department(db_path: Path) -> None:
    """create_task без department_id → department_id='dev'."""
    res = tools.create_task("Тест дефолт", db_path=db_path)
    assert res["статус"] == "ok"
    assert res["задача"]["department_id"] == "dev"


# ---------------------------------------------------------------------------
# Test 3: list_tasks(department_id='dev') — только dev задачи
# ---------------------------------------------------------------------------

def test_list_tasks_filter_dev(db_path: Path) -> None:
    """list_tasks(department_id='dev') возвращает только dev задачи."""
    # Создаём отдел marketing и задачу в нём
    tools.create_department("marketing", db_path=db_path)
    tools.create_task("dev-task", department_id="dev", db_path=db_path)
    tools.create_task("marketing-task", department_id="marketing", db_path=db_path)

    res = tools.list_tasks(department_id="dev", db_path=db_path)
    assert res["статус"] == "ok"
    titles = [t["title"] for t in res["задачи"]]
    assert "dev-task" in titles
    assert "marketing-task" not in titles


# ---------------------------------------------------------------------------
# Test 4: list_tasks(department_id=None) → все задачи
# ---------------------------------------------------------------------------

def test_list_tasks_no_filter_returns_all(db_path: Path) -> None:
    """list_tasks(department_id=None) возвращает все задачи всех отделов."""
    tools.create_department("marketing", db_path=db_path)
    tools.create_task("dev-task", department_id="dev", db_path=db_path)
    tools.create_task("marketing-task", department_id="marketing", db_path=db_path)

    res = tools.list_tasks(department_id=None, db_path=db_path)
    assert res["статус"] == "ok"
    titles = [t["title"] for t in res["задачи"]]
    assert "dev-task" in titles
    assert "marketing-task" in titles


# ---------------------------------------------------------------------------
# Test 5: chat_post() без department_id → пишет в dev channel
# ---------------------------------------------------------------------------

def test_chat_post_default_department(db_path: Path) -> None:
    """chat_post без department_id → сообщение в dev channel."""
    res = tools.chat_post("тимлид", "привет", db_path=db_path)
    assert res["статус"] == "ok"
    assert res["сообщение"]["department_id"] == "dev"


# ---------------------------------------------------------------------------
# Test 6: chat_recent(department_id=None) читает global channel
# ---------------------------------------------------------------------------

def test_chat_recent_global_channel(db_path: Path) -> None:
    """chat_recent(department_id=None) читает только глобальный канал (department_id IS NULL)."""
    # Пишем в dev и в глобальный канал
    tools.chat_post("тимлид", "dev-msg", department_id="dev", db_path=db_path)
    tools.chat_post("тимлид", "global-msg", department_id=None, db_path=db_path)

    res = tools.chat_recent(department_id=None, db_path=db_path)
    assert res["статус"] == "ok"
    texts = [m["text"] for m in res["сообщения"]]
    assert "global-msg" in texts
    assert "dev-msg" not in texts


# ---------------------------------------------------------------------------
# Test 7: create_department("marketing", ...) создаёт новый отдел
# ---------------------------------------------------------------------------

def test_create_department_marketing(db_path: Path) -> None:
    """create_department создаёт отдел с корректным slug и метаданными."""
    res = tools.create_department(
        "marketing",
        description="Маркетинговый отдел",
        icon="📣",
        db_path=db_path,
    )
    assert res["статус"] == "ok"
    dept = res["отдел"]
    assert dept["id"] == "marketing"
    assert dept["name"] == "marketing"
    assert dept["icon"] == "📣"
    assert dept["archived_at"] is None


def test_create_department_duplicate_name_error(db_path: Path) -> None:
    """create_department с дублирующимся именем → ошибка."""
    tools.create_department("marketing", db_path=db_path)
    res = tools.create_department("marketing", db_path=db_path)
    assert res["статус"] == "error"


# ---------------------------------------------------------------------------
# Test 8: get_department('dev') возвращает метаданные + роли
# ---------------------------------------------------------------------------

def test_get_department_dev(db_path: Path) -> None:
    """get_department('dev') возвращает метаданные dev и список ролей."""
    res = tools.get_department("dev", db_path=db_path)
    assert res["статус"] == "ok"
    dept = res["отдел"]
    assert dept["id"] == "dev"
    assert "roles" in dept
    # Роли по умолчанию для dev: тимлид, бэкенд и т.д.
    role_names = [r["name"] for r in dept["roles"]]
    assert len(role_names) > 0, "У отдела dev должны быть роли"


def test_get_department_not_found(db_path: Path) -> None:
    """get_department несуществующего отдела → not_found."""
    res = tools.get_department("nonexistent", db_path=db_path)
    assert res["статус"] == "not_found"


# ---------------------------------------------------------------------------
# Test 9: backward compat — старый вызов create_task без department_id
# ---------------------------------------------------------------------------

def test_create_task_backward_compat(db_path: Path) -> None:
    """Старый вызов create_task(title, description, ...) без department_id работает как раньше."""
    res = tools.create_task(
        title="Легаси задача",
        description="Без department_id",
        assignee="бэкенд",
        priority="P1",
        db_path=db_path,
    )
    assert res["статус"] == "ok"
    task = res["задача"]
    assert task["title"] == "Легаси задача"
    assert task["assignee"] == "бэкенд"
    assert task["priority"] == "P1"
    # department_id должен быть 'dev' (default)
    assert task["department_id"] == "dev"


# ---------------------------------------------------------------------------
# Test 10: list_tasks с department_id='marketing' не возвращает dev задачи
# ---------------------------------------------------------------------------

def test_list_tasks_marketing_excludes_dev(db_path: Path) -> None:
    """list_tasks(department_id='marketing') не возвращает задачи dev."""
    tools.create_department("marketing", db_path=db_path)
    tools.create_task("dev-only-task", department_id="dev", db_path=db_path)
    tools.create_task("marketing-only-task", department_id="marketing", db_path=db_path)

    res = tools.list_tasks(department_id="marketing", db_path=db_path)
    assert res["статус"] == "ok"
    titles = [t["title"] for t in res["задачи"]]
    assert "marketing-only-task" in titles
    assert "dev-only-task" not in titles, "dev задача не должна попасть в marketing filter"


# ---------------------------------------------------------------------------
# Test 11: get_task возвращает поле department_id (из S8.1 _row_to_task)
# ---------------------------------------------------------------------------

def test_get_task_contains_department_id(db_path: Path) -> None:
    """get_task() возвращает поле department_id."""
    created = tools.create_task("check dept field", department_id="dev", db_path=db_path)
    task_id = created["задача"]["id"]
    res = tools.get_task(task_id, db_path=db_path)
    assert res["статус"] == "ok"
    assert "department_id" in res["задача"]
    assert res["задача"]["department_id"] == "dev"


# ---------------------------------------------------------------------------
# Test 12: chat_post и chat_recent для dev channel изолированы от global
# ---------------------------------------------------------------------------

def test_chat_channels_isolation(db_path: Path) -> None:
    """Сообщения dev-канала не попадают в global и наоборот."""
    tools.chat_post("тимлид", "только dev", department_id="dev", db_path=db_path)
    tools.chat_post("тимлид", "только global", department_id=None, db_path=db_path)

    dev_msgs = tools.chat_recent(department_id="dev", db_path=db_path)["сообщения"]
    global_msgs = tools.chat_recent(department_id=None, db_path=db_path)["сообщения"]

    dev_texts = {m["text"] for m in dev_msgs}
    global_texts = {m["text"] for m in global_msgs}

    assert "только dev" in dev_texts
    assert "только global" not in dev_texts
    assert "только global" in global_texts
    assert "только dev" not in global_texts

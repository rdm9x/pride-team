"""Тесты SQLite-слоя: миграции, CRUD, индексы."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from pride_tasks import db


def test_init_db_creates_schema(tmp_path: Path) -> None:
    path = tmp_path / "tasks.db"
    db.init_db(path)
    assert path.exists(), "БД не создалась"
    conn = sqlite3.connect(path)
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    finally:
        conn.close()
    assert {"tasks", "task_comments", "roles"} <= tables


EXPECTED_ROLES = sorted(
    ["тимлид", "бэкенд", "qa", "архитектор", "frontend", "devops", "техписатель"]
)


def test_init_db_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "tasks.db"
    db.init_db(path)
    db.init_db(path)  # повторно — не должна падать или дубль вставлять роли
    roles = db.list_roles(path)
    names = [r["name"] for r in roles]
    assert sorted(names) == EXPECTED_ROLES


def test_default_roles_loaded(db_path: Path) -> None:
    roles = db.list_roles(db_path)
    assert len(roles) == len(EXPECTED_ROLES)
    by_name = {r["name"]: r for r in roles}
    assert "python" in by_name["бэкенд"]["capabilities"]
    assert "декомпозиция" in by_name["тимлид"]["capabilities"]
    assert "adr" in by_name["архитектор"]["capabilities"]
    assert "docker" in by_name["devops"]["capabilities"]


def test_insert_task_minimal(db_path: Path) -> None:
    task = db.insert_task(db_path, title="Привет")
    assert task["title"] == "Привет"
    assert task["status"] == "todo"
    assert task["priority"] == "P2"
    assert task["labels"] == []
    assert task["requires_approval"] is False
    assert len(task["id"]) == 12


def test_insert_task_full(db_path: Path) -> None:
    task = db.insert_task(
        db_path,
        title="Полная",
        description="детально",
        assignee="бэкенд",
        reporter="пользователь",
        priority="P1",
        requires_approval=True,
        status="needs_approval",
        labels=["approval", "git-push"],
    )
    assert task["assignee"] == "бэкенд"
    assert task["priority"] == "P1"
    assert task["requires_approval"] is True
    assert task["labels"] == ["approval", "git-push"]
    assert task["status"] == "needs_approval"


def test_get_task_with_history(db_path: Path) -> None:
    parent = db.insert_task(db_path, title="parent")
    child = db.insert_task(db_path, title="child", parent_id=parent["id"])
    db.add_comment(db_path, parent["id"], "тимлид", "стартую")
    db.add_comment(db_path, parent["id"], "бэкенд", "взял")
    fetched = db.get_task(db_path, parent["id"], with_history=True)
    assert fetched is not None
    assert len(fetched["comments"]) == 2
    assert fetched["comments"][0]["text"] == "стартую"
    assert len(fetched["subtasks"]) == 1
    assert fetched["subtasks"][0]["id"] == child["id"]


def test_list_tasks_filters(db_path: Path) -> None:
    db.insert_task(db_path, title="A", status="todo", assignee="бэкенд")
    db.insert_task(db_path, title="B", status="wip", assignee="бэкенд")
    db.insert_task(db_path, title="C", status="todo", assignee="qa")
    db.insert_task(db_path, title="D", status="todo", labels=["urgent"])

    assert len(db.list_tasks(db_path, status="todo")) == 3
    assert len(db.list_tasks(db_path, status="wip")) == 1
    assert len(db.list_tasks(db_path, assignee="бэкенд")) == 2
    assert len(db.list_tasks(db_path, label="urgent")) == 1
    assert len(db.list_tasks(db_path, limit=2)) == 2


def test_update_task_status_done_sets_completed_at(db_path: Path) -> None:
    task = db.insert_task(db_path, title="X")
    assert task["completed_at"] is None
    updated = db.update_task(db_path, task["id"], status="done")
    assert updated is not None
    assert updated["status"] == "done"
    assert updated["completed_at"] is not None


def test_update_task_rejects_unknown_field(db_path: Path) -> None:
    task = db.insert_task(db_path, title="X")
    with pytest.raises(ValueError, match="Недопустимые поля"):
        db.update_task(db_path, task["id"], some_weird_field="oops")


def test_update_task_not_found(db_path: Path) -> None:
    assert db.update_task(db_path, "deadbeef", status="done") is None


def test_claim_task_takes_unassigned(db_path: Path) -> None:
    task = db.insert_task(db_path, title="X")
    result = db.claim_task(db_path, task["id"], "бэкенд")
    assert result["ok"] is True
    assert result["task"]["assignee"] == "бэкенд"
    assert result["task"]["status"] == "wip"


def test_claim_task_idempotent_same_assignee(db_path: Path) -> None:
    task = db.insert_task(db_path, title="X", assignee="бэкенд", status="wip")
    result = db.claim_task(db_path, task["id"], "бэкенд")
    assert result["ok"] is True


def test_claim_task_conflict(db_path: Path) -> None:
    task = db.insert_task(db_path, title="X", assignee="бэкенд", status="wip")
    result = db.claim_task(db_path, task["id"], "qa")
    assert result["ok"] is False
    assert result["reason"] == "conflict"
    assert result["current_assignee"] == "бэкенд"


def test_claim_task_not_found(db_path: Path) -> None:
    result = db.claim_task(db_path, "deadbeef", "бэкенд")
    assert result["ok"] is False
    assert result["reason"] == "not_found"


def test_add_comment_and_history(db_path: Path) -> None:
    task = db.insert_task(db_path, title="X")
    c1 = db.add_comment(db_path, task["id"], "тимлид", "первый")
    c2 = db.add_comment(db_path, task["id"], "бэкенд", "второй")
    assert c1["id"] != c2["id"]
    fetched = db.get_task(db_path, task["id"], with_history=True)
    assert [c["text"] for c in fetched["comments"]] == ["первый", "второй"]


def test_add_comment_unknown_task_raises(db_path: Path) -> None:
    with pytest.raises(KeyError):
        db.add_comment(db_path, "deadbeef", "тимлид", "hi")


def test_submit_result_status_change(db_path: Path) -> None:
    task = db.insert_task(db_path, title="X", assignee="бэкенд", status="wip")
    result = db.submit_result(
        db_path,
        task["id"],
        {"статус": "ok", "файлы": ["a.py"]},
        new_status="review",
    )
    assert result is not None
    assert result["status"] == "review"
    assert result["result"] == {"статус": "ok", "файлы": ["a.py"]}


def test_submit_result_keeps_status_when_none(db_path: Path) -> None:
    task = db.insert_task(db_path, title="X", status="wip")
    result = db.submit_result(db_path, task["id"], {"k": "v"})
    assert result["status"] == "wip"


def test_submit_result_done_sets_completed_at(db_path: Path) -> None:
    task = db.insert_task(db_path, title="X", status="wip")
    result = db.submit_result(db_path, task["id"], {"k": "v"}, new_status="done")
    assert result["completed_at"] is not None


def test_labels_are_json_serialized(db_path: Path) -> None:
    db.insert_task(db_path, title="X", labels=["approval", "git-push"])
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT labels FROM tasks WHERE title = 'X'").fetchone()
    finally:
        conn.close()
    assert json.loads(row[0]) == ["approval", "git-push"]


def test_atomic_modify_basic(db_path: Path) -> None:
    task = db.insert_task(db_path, title="X")

    def add_label(t: dict) -> dict:
        return {"labels": (t["labels"] or []) + ["новая"]}

    updated = db.atomic_modify(db_path, task["id"], add_label)
    assert updated["labels"] == ["новая"]


def test_atomic_modify_none_for_missing(db_path: Path) -> None:
    assert db.atomic_modify(db_path, "deadbeef", lambda t: {}) is None


def test_dependency_basic(db_path: Path) -> None:
    a = db.insert_task(db_path, title="A")
    b = db.insert_task(db_path, title="B")
    res = db.add_dependency(db_path, b["id"], a["id"])
    assert res["ok"] is True
    blockers = db.get_blockers(db_path, b["id"])
    assert len(blockers) == 1 and blockers[0]["id"] == a["id"]
    blocking = db.get_blocking(db_path, a["id"])
    assert len(blocking) == 1 and blocking[0]["id"] == b["id"]
    assert db.is_blocked(db_path, b["id"]) is True
    assert db.is_blocked(db_path, a["id"]) is False


def test_dependency_self_rejected(db_path: Path) -> None:
    a = db.insert_task(db_path, title="A")
    res = db.add_dependency(db_path, a["id"], a["id"])
    assert res["ok"] is False and "самозависимость" in res["reason"]


def test_dependency_cycle_rejected(db_path: Path) -> None:
    a = db.insert_task(db_path, title="A")
    b = db.insert_task(db_path, title="B")
    c = db.insert_task(db_path, title="C")
    # A → B → C, попытка C → A создаст цикл
    assert db.add_dependency(db_path, b["id"], a["id"])["ok"]
    assert db.add_dependency(db_path, c["id"], b["id"])["ok"]
    res = db.add_dependency(db_path, a["id"], c["id"])
    assert res["ok"] is False and "цикл" in res["reason"]


def test_dependency_unknown_task(db_path: Path) -> None:
    a = db.insert_task(db_path, title="A")
    res = db.add_dependency(db_path, a["id"], "deadbeef")
    assert res["ok"] is False and "не существует" in res["reason"]


def test_dependency_blockers_filter_done(db_path: Path) -> None:
    a = db.insert_task(db_path, title="A")
    b = db.insert_task(db_path, title="B")
    db.add_dependency(db_path, b["id"], a["id"])
    db.update_task(db_path, a["id"], status="done")
    # done-задача не блокирует
    assert db.is_blocked(db_path, b["id"]) is False


def test_dependency_remove(db_path: Path) -> None:
    a = db.insert_task(db_path, title="A")
    b = db.insert_task(db_path, title="B")
    db.add_dependency(db_path, b["id"], a["id"])
    assert db.remove_dependency(db_path, b["id"], a["id"]) is True
    assert db.is_blocked(db_path, b["id"]) is False


def test_get_task_with_history_includes_deps(db_path: Path) -> None:
    a = db.insert_task(db_path, title="A")
    b = db.insert_task(db_path, title="B")
    db.add_dependency(db_path, b["id"], a["id"])
    fetched = db.get_task(db_path, b["id"], with_history=True)
    assert len(fetched["blocked_by"]) == 1
    assert fetched["blocked_by"][0]["id"] == a["id"]


def test_delete_task_cleans_comments(db_path: Path) -> None:
    task = db.insert_task(db_path, title="X")
    db.add_comment(db_path, task["id"], "тимлид", "к")
    assert db.delete_task(db_path, task["id"]) is True
    assert db.get_task(db_path, task["id"]) is None
    conn = sqlite3.connect(db_path)
    try:
        cnt = conn.execute(
            "SELECT COUNT(*) FROM task_comments WHERE task_id = ?", (task["id"],)
        ).fetchone()[0]
    finally:
        conn.close()
    assert cnt == 0

"""Тесты публичных tool-функций (то что отдаётся в MCP)."""

from __future__ import annotations

from pathlib import Path

import pytest

from pride_tasks import tools


def test_list_tasks_empty(db_path: Path) -> None:
    res = tools.list_tasks(db_path=db_path)
    assert res["статус"] == "ok"
    assert res["всего"] == 0


def test_list_tasks_bad_status(db_path: Path) -> None:
    res = tools.list_tasks(status="мусор", db_path=db_path)
    assert res["статус"] == "error"


def test_create_task_minimal(db_path: Path) -> None:
    res = tools.create_task(title="hi", db_path=db_path)
    assert res["статус"] == "ok"
    assert res["задача"]["title"] == "hi"


def test_create_task_empty_title(db_path: Path) -> None:
    res = tools.create_task(title="   ", db_path=db_path)
    assert res["статус"] == "error"


def test_create_task_bad_assignee(db_path: Path) -> None:
    res = tools.create_task(title="X", assignee="hacker", db_path=db_path)
    assert res["статус"] == "error"


def test_create_task_unknown_parent(db_path: Path) -> None:
    res = tools.create_task(title="X", parent_id="deadbeef", db_path=db_path)
    assert res["статус"] == "error"


def test_create_subtask(db_path: Path) -> None:
    p = tools.create_task(title="parent", db_path=db_path)
    c = tools.create_task(title="child", parent_id=p["задача"]["id"], db_path=db_path)
    assert c["статус"] == "ok"
    assert c["задача"]["parent_id"] == p["задача"]["id"]


def test_get_task_not_found(db_path: Path) -> None:
    res = tools.get_task("deadbeef", db_path=db_path)
    assert res["статус"] == "not_found"


def test_get_task_with_history(db_path: Path) -> None:
    p = tools.create_task(title="parent", db_path=db_path)
    pid = p["задача"]["id"]
    tools.add_comment(pid, "тимлид", "стартую", db_path=db_path)
    tools.create_task(title="child", parent_id=pid, db_path=db_path)
    res = tools.get_task(pid, db_path=db_path)
    assert res["статус"] == "ok"
    assert len(res["задача"]["comments"]) == 1
    assert len(res["задача"]["subtasks"]) == 1


def test_update_task_happy(db_path: Path) -> None:
    t = tools.create_task(title="X", db_path=db_path)
    res = tools.update_task(t["задача"]["id"], status="wip", assignee="бэкенд", db_path=db_path)
    assert res["статус"] == "ok"
    assert res["задача"]["status"] == "wip"
    assert res["задача"]["assignee"] == "бэкенд"


def test_update_task_bad_status(db_path: Path) -> None:
    t = tools.create_task(title="X", db_path=db_path)
    res = tools.update_task(t["задача"]["id"], status="мусор", db_path=db_path)
    assert res["статус"] == "error"


def test_update_task_not_found(db_path: Path) -> None:
    res = tools.update_task("deadbeef", status="done", db_path=db_path)
    assert res["статус"] == "not_found"


def test_claim_task_happy(db_path: Path) -> None:
    t = tools.create_task(title="X", db_path=db_path)
    res = tools.claim_task(t["задача"]["id"], "бэкенд", db_path=db_path)
    assert res["статус"] == "ok"
    assert res["задача"]["assignee"] == "бэкенд"


def test_claim_task_conflict(db_path: Path) -> None:
    t = tools.create_task(title="X", db_path=db_path)
    tools.claim_task(t["задача"]["id"], "бэкенд", db_path=db_path)
    res = tools.claim_task(t["задача"]["id"], "qa", db_path=db_path)
    assert res["статус"] == "конфликт"


def test_claim_task_bad_role(db_path: Path) -> None:
    t = tools.create_task(title="X", db_path=db_path)
    res = tools.claim_task(t["задача"]["id"], "hacker", db_path=db_path)
    assert res["статус"] == "error"


def test_add_comment_happy(db_path: Path) -> None:
    t = tools.create_task(title="X", db_path=db_path)
    res = tools.add_comment(t["задача"]["id"], "тимлид", "hi", db_path=db_path)
    assert res["статус"] == "ok"
    assert res["комментарий"]["text"] == "hi"


def test_add_comment_empty_text(db_path: Path) -> None:
    t = tools.create_task(title="X", db_path=db_path)
    res = tools.add_comment(t["задача"]["id"], "тимлид", "  ", db_path=db_path)
    assert res["статус"] == "error"


def test_add_comment_unknown_author(db_path: Path) -> None:
    t = tools.create_task(title="X", db_path=db_path)
    res = tools.add_comment(t["задача"]["id"], "hacker", "hi", db_path=db_path)
    assert res["статус"] == "error"


def test_add_comment_not_found(db_path: Path) -> None:
    res = tools.add_comment("deadbeef", "тимлид", "hi", db_path=db_path)
    assert res["статус"] == "not_found"


def test_submit_result_happy(db_path: Path) -> None:
    t = tools.create_task(title="X", db_path=db_path)
    res = tools.submit_result(
        t["задача"]["id"], {"статус": "ok", "файлы": ["a.py"]}, "review", db_path=db_path
    )
    assert res["статус"] == "ok"
    assert res["задача"]["status"] == "review"


def test_submit_result_bad_type(db_path: Path) -> None:
    t = tools.create_task(title="X", db_path=db_path)
    res = tools.submit_result(t["задача"]["id"], "не_dict", db_path=db_path)  # type: ignore[arg-type]
    assert res["статус"] == "error"


def test_list_roles(db_path: Path) -> None:
    res = tools.list_roles(db_path=db_path)
    assert res["статус"] == "ok"
    assert res["всего"] == 7
    names = sorted([r["name"] for r in res["роли"]])
    assert names == sorted([
        "тимлид", "бэкенд", "qa",
        "архитектор", "frontend", "devops", "техписатель",
    ])


def test_approval_gate_flow(db_path: Path) -> None:
    """Mini-сценарий approval-gate из approval_gates.md."""
    # Бэкенд создал родительскую задачу
    parent = tools.create_task(
        title="webhook impl", assignee="бэкенд", db_path=db_path
    )
    pid = parent["задача"]["id"]
    # Просит approval на git push
    approval = tools.create_task(
        title="git push origin main",
        description="бэкенд просит push",
        assignee="дмитрий",
        parent_id=pid,
        status="needs_approval",
        requires_approval=True,
        labels=["approval", "git-push"],
        db_path=db_path,
    )
    assert approval["статус"] == "ok"
    assert approval["задача"]["status"] == "needs_approval"
    aid = approval["задача"]["id"]
    # Дмитрий approve через update_task → wip
    tools.update_task(aid, status="wip", db_path=db_path)
    tools.add_comment(aid, "дмитрий", "approved", db_path=db_path)
    # Бэкенд сделал push → submit_result → done
    res = tools.submit_result(
        aid, {"git_push": "ok", "sha": "abc123"}, "done", db_path=db_path
    )
    assert res["задача"]["status"] == "done"
    assert res["задача"]["completed_at"] is not None

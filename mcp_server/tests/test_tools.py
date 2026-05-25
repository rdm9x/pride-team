"""Тесты публичных tool-функций (то что отдаётся в MCP)."""

from __future__ import annotations

from pathlib import Path

import pytest

from devboard_tasks import tools


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
    # ADR-009 Phase 1.7: role renamed тимлид → dev-lead after DB migration.
    assert names == sorted([
        "dev-lead", "бэкенд", "qa",
        "архитектор", "frontend", "devops", "техписатель",
    ])


def test_approval_gate_flow(db_path: Path) -> None:
    """Mini-сценарий approval-gate из approval_gates.md.

    После введения safety-net submit_result(new_status='done') через MCP
    переводит задачу в 'review', а не в 'done' — owner-acceptance обязателен.
    """
    # Бэкенд создал родительскую задачу
    parent = tools.create_task(
        title="webhook impl", assignee="бэкенд", db_path=db_path
    )
    pid = parent["задача"]["id"]
    # Просит approval на git push
    approval = tools.create_task(
        title="git push origin main",
        description="бэкенд просит push",
        assignee="пользователь",
        parent_id=pid,
        status="needs_approval",
        requires_approval=True,
        labels=["approval", "git-push"],
        db_path=db_path,
    )
    assert approval["статус"] == "ok"
    assert approval["задача"]["status"] == "needs_approval"
    aid = approval["задача"]["id"]
    # пользователь approve через update_task → wip
    tools.update_task(aid, status="wip", db_path=db_path)
    tools.add_comment(aid, "пользователь", "approved", db_path=db_path)
    # Бэкенд сделал push → submit_result(done) → safety-net → review
    res = tools.submit_result(
        aid, {"git_push": "ok", "sha": "abc123"}, "done", db_path=db_path
    )
    # Safety-net: done через MCP → review
    assert res["задача"]["status"] == "review"
    # completed_at не выставляется (задача не done)
    assert res["задача"]["completed_at"] is None


# === Safety-net: done через MCP запрещён ===


def test_safety_net_update_task_done_blocked(db_path: Path) -> None:
    """update_task(status='done') через MCP → задача в review, не done."""
    t = tools.create_task(title="Safety test task", assignee="бэкенд", db_path=db_path)
    tid = t["задача"]["id"]

    res = tools.update_task(tid, status="done", db_path=db_path)

    assert res["статус"] == "ok"
    assert res["задача"]["status"] == "review", "safety-net должен перевести в review"
    assert res["задача"]["completed_at"] is None


def test_safety_net_update_task_done_system_comment(db_path: Path) -> None:
    """update_task(status='done') → в истории задачи появляется system-комментарий."""
    from devboard_tasks import db as _db

    t = tools.create_task(title="Needs comment check", db_path=db_path)
    tid = t["задача"]["id"]

    tools.update_task(tid, status="done", db_path=db_path)

    task = _db.get_task(db_path, tid, with_history=True)
    system_comments = [c for c in task["comments"] if c["author"] == "system"]
    assert system_comments, "safety-net должен вставить system-комментарий"
    assert "safety-net" in system_comments[0]["text"].lower() or "Safety-net" in system_comments[0]["text"]


def test_safety_net_update_task_done_chat_alert(db_path: Path) -> None:
    """update_task(status='done') → алерт появляется в чате от system."""
    from devboard_tasks import db as _db

    t = tools.create_task(title="Chat alert task", db_path=db_path)
    tid = t["задача"]["id"]

    tools.update_task(tid, status="done", db_path=db_path)

    msgs = _db.list_chat_messages(db_path)
    system_msgs = [m for m in msgs if m["author"] == "system"]
    assert system_msgs, "safety-net должен отправить сообщение в чат"
    assert "Safety-net" in system_msgs[0]["text"] or "safety-net" in system_msgs[0]["text"]
    assert "review" in system_msgs[0]["text"]


def test_safety_net_submit_result_done_blocked(db_path: Path) -> None:
    """submit_result(new_status='done') через MCP → задача в review, не done."""
    t = tools.create_task(title="Submit safety test", db_path=db_path)
    tid = t["задача"]["id"]

    res = tools.submit_result(tid, {"файлы": ["main.py"]}, "done", db_path=db_path)

    assert res["статус"] == "ok"
    assert res["задача"]["status"] == "review", "safety-net должен перевести в review"
    assert res["задача"]["completed_at"] is None


def test_safety_net_submit_result_done_system_comment(db_path: Path) -> None:
    """submit_result(new_status='done') → system-комментарий в задаче."""
    from devboard_tasks import db as _db

    t = tools.create_task(title="Submit with comment", db_path=db_path)
    tid = t["задача"]["id"]

    tools.submit_result(tid, {"ok": True}, "done", db_path=db_path)

    task = _db.get_task(db_path, tid, with_history=True)
    system_comments = [c for c in task["comments"] if c["author"] == "system"]
    assert system_comments, "safety-net должен вставить system-комментарий"


def test_safety_net_already_done_not_affected(db_path: Path) -> None:
    """Задача уже в done → safety-net не срабатывает повторно (edge case)."""
    from devboard_tasks import db as _db

    t = tools.create_task(title="Already done task", db_path=db_path)
    tid = t["задача"]["id"]
    # Напрямую через db (минуя MCP-safety-net) поставим done
    _db.update_task(db_path, tid, status="done")

    # Теперь через MCP — safety-net не должен снова трогать её
    res = tools.update_task(tid, status="done", db_path=db_path)

    assert res["статус"] == "ok"
    assert res["задача"]["status"] == "done", "задача уже была done — не трогаем"
    # Никаких system-комментариев быть не должно
    task = _db.get_task(db_path, tid, with_history=True)
    system_comments = [c for c in task["comments"] if c["author"] == "system"]
    assert not system_comments, "edge case: уже done → safety-net не должен срабатывать"

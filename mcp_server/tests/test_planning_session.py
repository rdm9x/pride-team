"""Тесты 4 planning MCP-tools (B3, ADR-009 §2.4 + §2.6).

Покрытие:
  - list_all_inboxes happy path + role gate.
  - start_planning_session: 1 отдел / 3 отдела / role gate / некорректные параметры.
  - collect_planning_responses: реплики собираются в правильном порядке,
    приглашения Управляющего исключаются.
  - finalize_planning_session: cross-task'и создаются с
    requester_role_slug='managing-director', phase → 'done'.
  - Полный интеграционный flow: gathering → discussion → done.
  - Role gate для всех 4 tool'ов.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from devboard_tasks import db, tools


_MD_ROLE = "managing-director"


# === Фикстуры ===


@pytest.fixture()
def three_depts(db_path: Path) -> list[str]:
    """Создаёт три отдела (marketing, design, legal) и возвращает их id."""
    ids = []
    for name in ("Marketing", "Design", "Legal"):
        d = db.create_department(db_path, dept_id=name.lower(), name=name)
        ids.append(d["id"])
    return ids


# === list_all_inboxes ===


def test_list_all_inboxes_role_gate_denies_non_md(db_path: Path) -> None:
    """Любая роль кроме managing-director получает forbidden."""
    for role in (None, "тимлид", "qa", "owner", "marketing-lead"):
        res = tools.list_all_inboxes(caller_role=role, db_path=db_path)
        assert res["статус"] == "forbidden", role


def test_list_all_inboxes_happy_path_multiple_depts(
    db_path: Path, three_depts: list[str]
) -> None:
    """С 'dev' + 3 новыми отделами + задачами в разных статусах."""
    marketing, design, legal = three_depts
    # Накидаем задач разных статусов.
    tools.create_task(title="A", department_id="marketing", status="wip", db_path=db_path)
    tools.create_task(title="B", department_id="marketing", status="wip", db_path=db_path)
    tools.create_task(title="C", department_id="marketing", status="review", db_path=db_path)
    tools.create_task(title="D", department_id="design",    status="blocked", db_path=db_path)
    tools.create_task(title="E", department_id="legal",     status="todo", db_path=db_path)  # не считается ни в wip/review/blocked

    # Чат-сообщение для marketing — для last_chat_msg_time.
    db.post_chat_message(db_path, "system", "hello", department_id="marketing")

    res = tools.list_all_inboxes(caller_role=_MD_ROLE, db_path=db_path)
    assert res["статус"] == "ok"
    inboxes = {ib["dept_id"]: ib for ib in res["inboxes"]}
    # dev (default) + 3 новых = 4.
    assert {"dev", "marketing", "design", "legal"} <= set(inboxes.keys())
    assert inboxes["marketing"]["wip"] == 2
    assert inboxes["marketing"]["review"] == 1
    assert inboxes["marketing"]["blocked"] == 0
    assert inboxes["design"]["blocked"] == 1
    assert inboxes["legal"]["wip"] == 0  # todo не считается
    assert inboxes["marketing"]["last_chat_msg_time"] is not None
    assert inboxes["design"]["last_chat_msg_time"] is None


# === start_planning_session ===


def test_start_planning_session_role_gate(db_path: Path, three_depts: list[str]) -> None:
    """Только managing-director может стартовать планёрку."""
    for role in (None, "тимлид", "marketing-lead", "owner"):
        res = tools.start_planning_session(
            "test", ["marketing"], caller_role=role, db_path=db_path
        )
        assert res["статус"] == "forbidden", role


def test_start_planning_session_single_dept(db_path: Path, three_depts: list[str]) -> None:
    """С одним отделом — создаётся 1 запись + 1 chat_post."""
    res = tools.start_planning_session(
        "нужен лендинг", ["marketing"], caller_role=_MD_ROLE, db_path=db_path
    )
    assert res["статус"] == "ok"
    assert res["session_id"]
    assert res["сессия"]["phase"] == "gathering"
    assert res["сессия"]["departments_involved"] == ["marketing"]
    assert len(res["приглашения"]) == 1
    assert res["приглашения"][0]["dept_id"] == "marketing"
    assert "message_id" in res["приглашения"][0]
    # Проверяем что сообщение действительно лежит в чате отдела.
    msgs = db.list_chat_messages(db_path, department_id="marketing", limit=10)
    assert len(msgs) == 1
    assert msgs[0]["author"] == "managing-director"
    assert "Планёрка" in msgs[0]["text"]


def test_start_planning_session_three_depts(db_path: Path, three_depts: list[str]) -> None:
    """С тремя отделами — 3 chat_post'а в 3 разных чата."""
    res = tools.start_planning_session(
        "лендинг с юристами", ["marketing", "design", "legal"],
        caller_role=_MD_ROLE, db_path=db_path,
    )
    assert res["статус"] == "ok"
    assert len(res["приглашения"]) == 3
    # Все три чата получили приглашения.
    for dept_id in ("marketing", "design", "legal"):
        msgs = db.list_chat_messages(db_path, department_id=dept_id, limit=10)
        assert len(msgs) == 1, dept_id
        assert msgs[0]["author"] == "managing-director", dept_id


def test_start_planning_session_empty_owner_request(db_path: Path, three_depts: list[str]) -> None:
    """Пустой owner_request → error."""
    res = tools.start_planning_session(
        "  ", ["marketing"], caller_role=_MD_ROLE, db_path=db_path
    )
    assert res["статус"] == "error"


def test_start_planning_session_empty_departments(db_path: Path) -> None:
    """Пустой список отделов → error."""
    res = tools.start_planning_session(
        "x", [], caller_role=_MD_ROLE, db_path=db_path
    )
    assert res["статус"] == "error"


def test_start_planning_session_unknown_dept(db_path: Path) -> None:
    """Несуществующий dept_id → error, запись не создаётся."""
    res = tools.start_planning_session(
        "x", ["nope-not-a-dept"], caller_role=_MD_ROLE, db_path=db_path
    )
    assert res["статус"] == "error"


# === collect_planning_responses ===


def test_collect_planning_responses_role_gate(db_path: Path, three_depts: list[str]) -> None:
    """Только managing-director может собирать ответы."""
    start = tools.start_planning_session(
        "x", ["marketing"], caller_role=_MD_ROLE, db_path=db_path
    )
    sid = start["session_id"]
    res = tools.collect_planning_responses(sid, caller_role="qa", db_path=db_path)
    assert res["статус"] == "forbidden"


def test_collect_planning_responses_not_found(db_path: Path) -> None:
    res = tools.collect_planning_responses(
        "deadbeef0000", caller_role=_MD_ROLE, db_path=db_path
    )
    assert res["статус"] == "not_found"


def test_collect_planning_responses_collects_in_order(
    db_path: Path, three_depts: list[str]
) -> None:
    """Реплики из 2 отделов собираются хронологически, приглашения исключаются."""
    start = tools.start_planning_session(
        "лендинг", ["marketing", "design"],
        caller_role=_MD_ROLE, db_path=db_path,
    )
    sid = start["session_id"]

    # Имитируем реплики лидов в разном порядке с разными ts.
    # post_chat_message использует int(time.time()), который на secund-grained,
    # поэтому делаем sleep чтобы гарантировать порядок (или вставляем напрямую).
    db.post_chat_message(db_path, "тимлид", "marketing-lead reply 1", department_id="marketing")
    time.sleep(1.01)
    db.post_chat_message(db_path, "тимлид", "design-lead reply 1", department_id="design")
    time.sleep(1.01)
    db.post_chat_message(db_path, "тимлид", "marketing-lead reply 2", department_id="marketing")

    res = tools.collect_planning_responses(sid, caller_role=_MD_ROLE, db_path=db_path)
    assert res["статус"] == "ok"
    log = res["discussion_log"]
    # 3 реплики (приглашения Управляющего исключены).
    assert len(log) == 3
    # Хронологический порядок.
    assert log[0]["text"] == "marketing-lead reply 1"
    assert log[0]["dept"] == "marketing"
    assert log[1]["text"] == "design-lead reply 1"
    assert log[1]["dept"] == "design"
    assert log[2]["text"] == "marketing-lead reply 2"
    # Phase обновился на discussion.
    assert res["сессия"]["phase"] == "discussion"
    # И в БД тоже.
    session = db.planning_session_get(db_path, sid)
    assert session["phase"] == "discussion"
    assert len(session["discussion_log"]) == 3


# === finalize_planning_session ===


def test_finalize_planning_session_role_gate(db_path: Path, three_depts: list[str]) -> None:
    """Только managing-director может финализировать."""
    start = tools.start_planning_session(
        "x", ["marketing"], caller_role=_MD_ROLE, db_path=db_path
    )
    res = tools.finalize_planning_session(
        start["session_id"], "answer", caller_role="frontend", db_path=db_path
    )
    assert res["статус"] == "forbidden"


def test_finalize_planning_session_creates_cross_tasks_per_section(
    db_path: Path, three_depts: list[str]
) -> None:
    """С заголовками 'marketing:' и 'design:' → 2 задачи в 2 отдела."""
    start = tools.start_planning_session(
        "лендинг", ["marketing", "design"],
        caller_role=_MD_ROLE, db_path=db_path,
    )
    sid = start["session_id"]
    owner_answer = (
        "marketing: бюджет 500к, ЦА B2B, USP — скорость монтажа\n"
        "design: тёмная тема, минимализм, акцент на фото"
    )

    res = tools.finalize_planning_session(
        sid, owner_answer, caller_role=_MD_ROLE, db_path=db_path
    )
    assert res["статус"] == "ok"
    assert res["status"] == "done"
    created = res["created_tasks"]
    # 2 секции → 2 задачи.
    assert len(created) == 2
    by_dept = {c["dept"]: c for c in created}
    assert "marketing" in by_dept and "design" in by_dept
    assert "task_id" in by_dept["marketing"]
    assert "task_id" in by_dept["design"]
    # Проверяем что задачи действительно в БД.
    mt = db.get_task(db_path, by_dept["marketing"]["task_id"])
    assert mt is not None
    assert mt["department_id"] == "marketing"
    assert mt["requester_role_slug"] == "managing-director"
    assert mt["requester_department_id"] is None
    assert "бюджет" in mt["description"]
    assert mt["status"] == "todo"
    # planning_sessions обновлён.
    assert res["сессия"]["phase"] == "done"
    assert res["сессия"]["finished_at"] is not None
    assert res["сессия"]["owner_answer"] == owner_answer


def test_finalize_planning_session_fallback_no_headers(
    db_path: Path, three_depts: list[str]
) -> None:
    """Без заголовков — одна общая задача каждому отделу."""
    start = tools.start_planning_session(
        "x", ["marketing", "design"], caller_role=_MD_ROLE, db_path=db_path
    )
    sid = start["session_id"]
    res = tools.finalize_planning_session(
        sid, "просто описание задачи без секций", caller_role=_MD_ROLE, db_path=db_path
    )
    assert res["статус"] == "ok"
    # Fallback: задача в каждый отдел.
    assert len(res["created_tasks"]) == 2
    assert {c["dept"] for c in res["created_tasks"]} == {"marketing", "design"}


def test_finalize_planning_session_not_found(db_path: Path) -> None:
    res = tools.finalize_planning_session(
        "deadbeef0000", "answer", caller_role=_MD_ROLE, db_path=db_path
    )
    assert res["статус"] == "not_found"


def test_finalize_planning_session_empty_owner_answer(
    db_path: Path, three_depts: list[str]
) -> None:
    start = tools.start_planning_session(
        "x", ["marketing"], caller_role=_MD_ROLE, db_path=db_path
    )
    res = tools.finalize_planning_session(
        start["session_id"], "   ", caller_role=_MD_ROLE, db_path=db_path
    )
    assert res["статус"] == "error"


# === Полный интеграционный flow ===


def test_full_flow_gathering_discussion_done(
    db_path: Path, three_depts: list[str]
) -> None:
    """E2E: gathering → discussion → done.

    Phase 3 (consolidation) — это решение Управляющего на Claude-уровне,
    он не вызывает отдельного MCP-tool'а для неё (см. ADR-009 §2.6 — только 4 tools).
    distribution = finalize_planning_session.
    """
    # Phase 1: start
    start = tools.start_planning_session(
        "лендинг", ["marketing", "design", "legal"],
        caller_role=_MD_ROLE, db_path=db_path,
    )
    assert start["статус"] == "ok"
    sid = start["session_id"]
    assert db.planning_session_get(db_path, sid)["phase"] == "gathering"

    # Лиды пишут в чаты своих отделов.
    db.post_chat_message(db_path, "тимлид", "нужен бюджет и ЦА", department_id="marketing")
    time.sleep(1.01)
    db.post_chat_message(db_path, "тимлид", "стиль и палитра?", department_id="design")
    time.sleep(1.01)
    db.post_chat_message(db_path, "тимлид", "регионы размещения?", department_id="legal")

    # Phase 2: collect
    collect = tools.collect_planning_responses(sid, caller_role=_MD_ROLE, db_path=db_path)
    assert collect["статус"] == "ok"
    assert len(collect["discussion_log"]) == 3
    assert db.planning_session_get(db_path, sid)["phase"] == "discussion"

    # Phase 4: finalize (owner ответил)
    owner_answer = (
        "marketing: бюджет 500к, B2B, USP скорость\n"
        "design: тёмная, минимализм\n"
        "legal: 5 регионов МСК/СПб/Казань/Новосиб/Екб"
    )
    final = tools.finalize_planning_session(
        sid, owner_answer, caller_role=_MD_ROLE, db_path=db_path
    )
    assert final["статус"] == "ok"
    assert len(final["created_tasks"]) == 3
    # Все 3 задачи имеют requester_role_slug='managing-director'.
    for ct in final["created_tasks"]:
        task = db.get_task(db_path, ct["task_id"])
        assert task["requester_role_slug"] == "managing-director"
        assert task["department_id"] == ct["dept"]
    # Session — phase done + finished_at.
    final_session = db.planning_session_get(db_path, sid)
    assert final_session["phase"] == "done"
    assert final_session["finished_at"] is not None
    # created_tasks сохранены в БД.
    assert len(final_session["created_tasks"]) == 3

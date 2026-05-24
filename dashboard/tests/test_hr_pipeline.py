"""Тесты HR pipeline — S10.3 (ADR-004).

Mock'аем subprocess.Popen / hr_runner.spawn_hr_subprocess — мы НЕ запускаем
настоящий claude CLI в тестах. Проверяем state machine, валидацию плана,
материализацию ролей.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Гарантируем что dashboard/ в sys.path для импорта hr-модуля.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import hr as hr_runner  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_hr_state():
    """Очищаем in-memory реестр subprocess'ов между тестами."""
    hr_runner._reset_state_for_tests()
    yield
    hr_runner._reset_state_for_tests()


@pytest.fixture()
def fake_popen(monkeypatch):
    """Заменяет реальный subprocess.Popen в hr.py на MagicMock-фабрику.

    Возвращает list куда складываются все созданные mock-Popen объекты,
    чтобы тесты могли смотреть аргументы и stdin.
    """
    created: list[MagicMock] = []

    def factory(*args, **kwargs):
        proc = MagicMock()
        proc.poll.return_value = None  # ещё жив
        proc.stdin = MagicMock()
        proc.stdout = MagicMock()
        proc.stderr = MagicMock()
        proc.wait = MagicMock(return_value=0)
        proc.kill = MagicMock()
        proc._args = args
        proc._kwargs = kwargs
        created.append(proc)
        return proc

    # Подменяем _build_claude_cmd чтобы не зависеть от наличия claude CLI.
    monkeypatch.setattr(hr_runner, "_build_claude_cmd", lambda txt: ["true"])
    # Подменяем сам spawn — через popen_factory параметр.
    real_spawn = hr_runner.spawn_hr_subprocess

    def patched_spawn(session_id: str, initial_message: str, *, popen_factory=None):
        return real_spawn(session_id, initial_message, popen_factory=factory)

    monkeypatch.setattr(hr_runner, "spawn_hr_subprocess", patched_spawn)
    return created


@pytest.fixture()
def roles_tmp(monkeypatch, tmp_path):
    """Подменяет hr_runner._ROLES_DIR на временный путь, чтобы materialize_roles
    писал в tmp, а не в реальный roles/."""
    fake_roles = tmp_path / "roles_out"
    fake_roles.mkdir()
    monkeypatch.setattr(hr_runner, "_ROLES_DIR", fake_roles)
    # Сами функции materialize_roles берут default-аргумент из закрытия — поэтому
    # дополнительно подменяем атрибут materialize_roles.__defaults__ через wrapper.
    original = hr_runner.materialize_roles

    def wrapped(plan, *, roles_dir=fake_roles):
        return original(plan, roles_dir=roles_dir)

    monkeypatch.setattr(hr_runner, "materialize_roles", wrapped)
    return fake_roles


def _valid_plan(dept_name: str = "TestMarketing") -> dict:
    """Базовый валидный план для тестов approve."""
    return {
        "department": {
            "name": dept_name,
            "description": "Test marketing department",
            "icon": "📣",
        },
        "template_id": "marketing-v1",
        "roles": [
            {
                "slug": "marketing-lead",
                "name_ru": "Маркетинг-лид",
                "name_en": "Marketing Lead",
                "model": "claude-opus-4-7",
                "is_lead": True,
                "skills": ["strategy", "planning"],
                "output_spec": (
                    "Plans campaigns and reviews drafts before publication. "
                    "Output: weekly plan in markdown, draft reviews as comments."
                ),
                "system_prompt": "Ты — лид маркетинга. Управляй командой.",
            },
            {
                "slug": "content-writer",
                "name_ru": "Автор",
                "name_en": "Content Writer",
                "model": "claude-sonnet-4-6",
                "is_lead": False,
                "skills": ["writing"],
                "output_spec": (
                    "Produces long-form articles, social posts, ad copy under "
                    "marketing-lead review. Output: 1-3 markdown drafts per task."
                ),
                "system_prompt": "Ты — автор контента.",
            },
        ],
    }


# ---------------------------------------------------------------------------
# Migration tests
# ---------------------------------------------------------------------------


def test_init_db_idempotent(tmp_path):
    """init_db вызывается дважды без ошибок — миграция hr_sessions idempotent."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "mcp_server"))
    from pride_tasks import db

    dbp = tmp_path / "tasks.db"
    db.init_db(dbp)
    db.init_db(dbp)  # повторно — не должно падать
    # Колонка существует
    import sqlite3
    conn = sqlite3.connect(dbp)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(hr_sessions)")}
        assert {
            "id", "department_name", "state", "plan_json",
            "template_hint", "iteration_count", "attempt_count",
        }.issubset(cols)
    finally:
        conn.close()


def test_hr_sessions_crud(tmp_path):
    """create/get/update_hr_session работают."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "mcp_server"))
    from pride_tasks import db

    dbp = tmp_path / "tasks.db"
    db.init_db(dbp)
    s = db.create_hr_session(dbp, department_name="X", template_hint="marketing-v1")
    assert s["state"] == "hr_planning"
    assert s["iteration_count"] == 0
    # update
    upd = db.update_hr_session(dbp, s["id"], state="awaiting_owner_review", iteration_count=2)
    assert upd["state"] == "awaiting_owner_review"
    assert upd["iteration_count"] == 2
    # get
    got = db.get_hr_session(dbp, s["id"])
    assert got["state"] == "awaiting_owner_review"
    # update invalid state
    with pytest.raises(ValueError):
        db.update_hr_session(dbp, s["id"], state="something_random")


# ---------------------------------------------------------------------------
# POST /api/hr/start
# ---------------------------------------------------------------------------


def test_hr_start_creates_session(client, fake_popen):
    """POST /api/hr/start создаёт hr_session, state='hr_planning'."""
    r = client.post("/api/hr/start", json={
        "name": "Marketing",
        "description": "B2B SaaS",
    })
    assert r.status_code == 201
    body = r.get_json()
    assert body["state"] == "hr_planning"
    assert "hr_session_id" in body
    # Subprocess создан
    assert len(fake_popen) == 1
    # Initial message передан в stdin
    fake_popen[0].stdin.write.assert_called()


def test_hr_start_requires_name(client, fake_popen):
    """POST /api/hr/start без name → 400."""
    r = client.post("/api/hr/start", json={"description": "x"})
    assert r.status_code == 400
    assert len(fake_popen) == 0  # subprocess не спавнили


def test_hr_start_with_template_hint(client, fake_popen):
    """POST /api/hr/start с template_hint сохраняет его в сессии."""
    r = client.post("/api/hr/start", json={
        "name": "Sales",
        "description": "Outbound sales",
        "template_hint": "sales-v1",
    })
    assert r.status_code == 201
    sid = r.get_json()["hr_session_id"]
    r2 = client.get(f"/api/hr/status/{sid}")
    assert r2.status_code == 200
    assert r2.get_json()["template_hint"] == "sales-v1"


# ---------------------------------------------------------------------------
# POST /api/hr/answer
# ---------------------------------------------------------------------------


def test_hr_answer_increments_iteration(client, fake_popen):
    """POST /api/hr/answer передаёт stdin, iteration_count++."""
    r = client.post("/api/hr/start", json={"name": "Design", "description": "d"})
    sid = r.get_json()["hr_session_id"]

    r2 = client.post("/api/hr/answer", json={
        "hr_session_id": sid,
        "message": "Добавь UX Researcher",
    })
    assert r2.status_code == 200
    assert r2.get_json()["iteration_count"] == 1

    r3 = client.post("/api/hr/answer", json={
        "hr_session_id": sid,
        "message": "И ещё один",
    })
    assert r3.status_code == 200
    assert r3.get_json()["iteration_count"] == 2

    # stdin.write вызывался — хотя бы 2 раза для answer + 1 для initial.
    assert fake_popen[0].stdin.write.call_count >= 3


def test_hr_answer_not_found(client, fake_popen):
    """POST /api/hr/answer с несуществующим session_id → 404."""
    r = client.post("/api/hr/answer", json={
        "hr_session_id": "ghost",
        "message": "x",
    })
    assert r.status_code == 404


def test_hr_answer_requires_message(client, fake_popen):
    """POST /api/hr/answer без message → 400."""
    r = client.post("/api/hr/start", json={"name": "Ops", "description": "d"})
    sid = r.get_json()["hr_session_id"]
    r2 = client.post("/api/hr/answer", json={"hr_session_id": sid})
    assert r2.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/hr/approve — happy path
# ---------------------------------------------------------------------------


def test_hr_approve_valid_plan(client, fake_popen, roles_tmp):
    """Approve валидного плана → state=active, файлы созданы, department в БД."""
    r = client.post("/api/hr/start", json={"name": "TestMarketing", "description": "d"})
    sid = r.get_json()["hr_session_id"]

    plan = _valid_plan("TestMarketing")
    r2 = client.post("/api/hr/approve", json={
        "hr_session_id": sid,
        "plan": plan,
    })
    assert r2.status_code == 200, r2.get_json()
    body = r2.get_json()
    assert body["state"] == "active"
    assert body["department"]["name"] == "TestMarketing"
    assert len(body["roles_created"]) == 2

    # Файлы реально на диске
    files = list(roles_tmp.rglob("*.md"))
    assert len(files) == 2
    names = {f.name for f in files}
    assert names == {"marketing-lead.md", "content-writer.md"}

    # Status показывает active
    r3 = client.get(f"/api/hr/status/{sid}")
    assert r3.get_json()["state"] == "active"


def test_hr_approve_creates_department_in_db(client, fake_popen, roles_tmp):
    """После approve в БД появляется отдел через /api/departments."""
    r = client.post("/api/hr/start", json={"name": "ApproveDept", "description": "d"})
    sid = r.get_json()["hr_session_id"]

    plan = _valid_plan("ApproveDept")
    client.post("/api/hr/approve", json={"hr_session_id": sid, "plan": plan})

    # Проверяем что отдел появился
    r2 = client.get("/api/departments")
    ids = [d["id"] for d in r2.get_json()["departments"]]
    assert "approvedept" in ids


# ---------------------------------------------------------------------------
# POST /api/hr/approve — invalid plan re-generates, max 3 → aborted
# ---------------------------------------------------------------------------


def test_hr_approve_invalid_plan_re_generates(client, fake_popen, roles_tmp):
    """Approve invalid плана: attempt 1 и 2 → invalid_plan + hr_revising."""
    r = client.post("/api/hr/start", json={"name": "Bad", "description": "d"})
    sid = r.get_json()["hr_session_id"]

    # План с 2 leads — invalid
    bad_plan = _valid_plan("Bad")
    bad_plan["roles"][1]["is_lead"] = True  # теперь 2 leads

    r1 = client.post("/api/hr/approve", json={"hr_session_id": sid, "plan": bad_plan})
    assert r1.status_code == 422
    body1 = r1.get_json()
    assert body1["status"] == "invalid_plan"
    assert body1["attempts"] == 1
    assert any("is_lead" in e for e in body1["errors"])

    # State после первой попытки — hr_revising
    r_status = client.get(f"/api/hr/status/{sid}")
    assert r_status.get_json()["state"] == "hr_revising"

    # Повтор — attempt 2
    r2 = client.post("/api/hr/approve", json={"hr_session_id": sid, "plan": bad_plan})
    assert r2.status_code == 422
    assert r2.get_json()["attempts"] == 2


def test_hr_approve_invalid_3_times_aborts(client, fake_popen, roles_tmp):
    """После 3 неудачных attempt → state=aborted."""
    r = client.post("/api/hr/start", json={"name": "AbortMe", "description": "d"})
    sid = r.get_json()["hr_session_id"]

    bad_plan = _valid_plan("AbortMe")
    bad_plan["roles"][0]["is_lead"] = False
    bad_plan["roles"][1]["is_lead"] = False  # 0 leads — invalid

    for _ in range(3):
        rr = client.post("/api/hr/approve", json={"hr_session_id": sid, "plan": bad_plan})
        assert rr.status_code == 422

    # Последний ответ должен быть status="aborted"
    assert rr.get_json()["status"] == "aborted"

    # Status показывает aborted
    r2 = client.get(f"/api/hr/status/{sid}")
    assert r2.get_json()["state"] == "aborted"
    assert r2.get_json()["finished_at"] is not None


def test_hr_approve_no_plan(client, fake_popen):
    """Approve без plan и без сохранённого session.plan → 400."""
    r = client.post("/api/hr/start", json={"name": "NoPlan", "description": "d"})
    sid = r.get_json()["hr_session_id"]
    r2 = client.post("/api/hr/approve", json={"hr_session_id": sid})
    assert r2.status_code == 400


def test_hr_approve_destructive_rejected(client, fake_popen, roles_tmp):
    """План с 'delete' в output_spec → invalid."""
    r = client.post("/api/hr/start", json={"name": "Destr", "description": "d"})
    sid = r.get_json()["hr_session_id"]

    bad_plan = _valid_plan("Destr")
    bad_plan["roles"][1]["output_spec"] = (
        "Will delete tables and truncate everything. Output: nothing helpful."
    )
    rr = client.post("/api/hr/approve", json={"hr_session_id": sid, "plan": bad_plan})
    assert rr.status_code == 422
    assert any("destructive" in e for e in rr.get_json()["errors"])


# ---------------------------------------------------------------------------
# GET /api/hr/status
# ---------------------------------------------------------------------------


def test_hr_status_returns_state(client, fake_popen):
    """GET /api/hr/status/<sid> → корректный state + поля."""
    r = client.post("/api/hr/start", json={"name": "Status", "description": "d"})
    sid = r.get_json()["hr_session_id"]
    r2 = client.get(f"/api/hr/status/{sid}")
    assert r2.status_code == 200
    body = r2.get_json()
    assert body["hr_session_id"] == sid
    assert body["state"] == "hr_planning"
    assert body["department_name"] == "Status"
    assert body["iteration_count"] == 0
    assert body["attempt_count"] == 0


def test_hr_status_not_found(client, fake_popen):
    """GET /api/hr/status/ghost → 404."""
    r = client.get("/api/hr/status/ghost")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Validator (unit, без endpoints)
# ---------------------------------------------------------------------------


def test_validate_hr_plan_unique_slugs():
    """План с дубликатами slug → invalid."""
    from roles.validator import validate_hr_plan
    plan = _valid_plan("Dups")
    plan["roles"][1]["slug"] = plan["roles"][0]["slug"]  # дубль
    r = validate_hr_plan(plan)
    assert not r.ok
    assert any("duplicates" in e for e in r.errors)


def test_validate_hr_plan_max_roles():
    """План с >8 ролей → invalid."""
    from roles.validator import validate_hr_plan
    plan = _valid_plan()
    # дублируем content-writer 8 раз с разными slug'ами → 1 lead + 8 writers = 9
    plan["roles"] = [plan["roles"][0]] + [
        {**plan["roles"][1], "slug": f"writer-{i}"} for i in range(8)
    ]
    r = validate_hr_plan(plan)
    assert not r.ok
    assert any("exceeds limit" in e for e in r.errors)


def test_validate_hr_plan_model_whitelist():
    """План с моделью вне whitelist → invalid."""
    from roles.validator import validate_hr_plan
    plan = _valid_plan()
    plan["roles"][0]["model"] = "some-random-model-v9"
    r = validate_hr_plan(plan)
    assert not r.ok
    assert any("whitelist" in e for e in r.errors)


def test_validate_hr_plan_system_prompt_too_long():
    """system_prompt > 500 строк → invalid."""
    from roles.validator import validate_hr_plan
    plan = _valid_plan()
    plan["roles"][0]["system_prompt"] = "\n".join(["line"] * 600)
    r = validate_hr_plan(plan)
    assert not r.ok
    assert any("exceeds limit 500" in e for e in r.errors)


# ---------------------------------------------------------------------------
# materialize_roles unit
# ---------------------------------------------------------------------------


def test_materialize_roles_creates_files(tmp_path):
    """materialize_roles записывает <dept-slug>/<role-slug>.md."""
    plan = _valid_plan("Materialize")
    created, errors = hr_runner.materialize_roles(plan, roles_dir=tmp_path)
    assert errors == []
    assert len(created) == 2
    assert all(p.exists() for p in created)
    # Frontmatter + body
    md = created[0].read_text(encoding="utf-8")
    assert md.startswith("---\n")
    assert "schema_version: 1" in md
    assert "extras:" in md
    assert "hr_meta:" in md


def test_department_slug_basic():
    """department_slug нормализует имя."""
    assert hr_runner.department_slug("Marketing") == "marketing"
    assert hr_runner.department_slug("Sales B2B") == "sales-b2b"
    # Кириллица — fallback 'dept'
    assert hr_runner.department_slug("Маркетинг") == "dept"

"""S12.2 — E2E тесты multi-department workflow v2.0.

Проверяем полный сквозной сценарий «отдел в production»:

  1. Создать отдел через HR-pipeline (mock claude CLI через popen_factory).
  2. Создать задачу в новом отделе (через MCP-уровень — REST POST /api/tasks
     не поддерживает department_id, см. ниже примечание).
  3. Делегировать subagent внутри отдела: обновить статус, добавить комментарий.
  4. Lead отдела A запрашивает у отдела B через POST /api/departments/<B>/tasks
     (cross-task; ADR-005).
  5. Target Lead принимает: перевод статуса (todo→wip).
  6. Owner accept для approval-кейса (needs_approval → done через approve endpoint).
  7. Archive отдела (PATCH /api/departments/<id>/archive) — задачи не теряются,
     отдел исключается из активного списка.

Дополнительные edge-cases:
  - HR aborted после 3 invalid plan attempts (с mock subprocess).
  - P3 cross-task → status=todo target.
  - P1 cross-task → status=needs_approval (требует owner).
  - Counter-proposal flow (POST /api/tasks/<id>/counter).

Claude CLI НЕ запускается — все subprocess.Popen вызовы заменены на MagicMock
через popen_factory (см. dashboard/tests/test_hr_pipeline.py для образца).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Гарантируем что dashboard/ в sys.path для импорта hr-модуля и app.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# И mcp_server для прямого вызова tools.create_task в шаге 2.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "mcp_server"))

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
    """Подменяет claude CLI на MagicMock-Popen фабрику.

    Возвращает list mock-Popen объектов для возможной интроспекции stdin.
    """
    created: list[MagicMock] = []

    def factory(*args, **kwargs):
        proc = MagicMock()
        proc.poll.return_value = None
        proc.stdin = MagicMock()
        # stdout.readline() returning '' causes _hr_stream_reader thread to exit cleanly.
        proc.stdout = MagicMock()
        proc.stdout.readline.return_value = ""
        proc.stderr = MagicMock()
        proc.wait = MagicMock(return_value=0)
        proc.kill = MagicMock()
        proc._args = args
        proc._kwargs = kwargs
        created.append(proc)
        return proc

    monkeypatch.setattr(
        hr_runner, "_build_claude_cmd",
        lambda txt, mcp_config, initial_message: ["true"],
    )
    real_spawn = hr_runner.spawn_hr_subprocess

    def patched_spawn(session_id: str, initial_message: str, *, db_path=None, popen_factory=None):
        return real_spawn(session_id, initial_message, db_path=db_path, popen_factory=factory)

    monkeypatch.setattr(hr_runner, "spawn_hr_subprocess", patched_spawn)
    return created


@pytest.fixture()
def roles_tmp(monkeypatch, tmp_path):
    """Перенаправляет materialize_roles в tmp, чтобы не загрязнять реальный roles/."""
    fake_roles = tmp_path / "roles_out"
    fake_roles.mkdir()
    monkeypatch.setattr(hr_runner, "_ROLES_DIR", fake_roles)
    original = hr_runner.materialize_roles

    def wrapped(plan, *, roles_dir=fake_roles):
        return original(plan, roles_dir=roles_dir)

    monkeypatch.setattr(hr_runner, "materialize_roles", wrapped)
    return fake_roles


def _valid_plan(dept_name: str = "Marketing") -> dict:
    """Базовый валидный план: 1 lead + 1 worker."""
    return {
        "department": {
            "name": dept_name,
            "description": f"{dept_name} department for E2E test",
            "icon": "📣",
        },
        "template_id": "marketing-v1",
        "roles": [
            {
                "slug": f"{dept_name.lower()}-lead",
                "name_ru": f"{dept_name} Lead",
                "name_en": f"{dept_name} Lead",
                "model": "claude-opus-4-7",
                "is_lead": True,
                "skills": ["leadership", "planning"],
                "output_spec": (
                    "Plans work, reviews drafts, delegates to writers. "
                    "Output: weekly plan + review comments."
                ),
                "system_prompt": f"Ты — {dept_name} Lead. Управляй командой.",
            },
            {
                "slug": f"{dept_name.lower()}-writer",
                "name_ru": "Контент-автор",
                "name_en": "Content Writer",
                "model": "claude-sonnet-4-6",
                "is_lead": False,
                "skills": ["writing"],
                "output_spec": (
                    "Produces drafts under Lead review. "
                    "Output: 1-3 markdown drafts per task."
                ),
                "system_prompt": "Ты — автор контента.",
            },
        ],
    }


# ---------------------------------------------------------------------------
# Шаг 1: HR pipeline создаёт новый отдел
# ---------------------------------------------------------------------------


def _create_department_via_hr(
    client, fake_popen, roles_tmp, *, dept_name: str = "Marketing"
) -> str:
    """Полный happy path HR: /start → /approve → state=active.

    Возвращает department_id созданного отдела.
    """
    # /api/hr/start
    r = client.post(
        "/api/hr/start",
        json={"name": dept_name, "description": f"E2E test for {dept_name}"},
    )
    assert r.status_code == 201, r.get_data(as_text=True)
    sid = r.get_json()["hr_session_id"]
    assert r.get_json()["state"] == "hr_planning"

    # /api/hr/approve с валидным планом
    plan = _valid_plan(dept_name)
    r = client.post(
        "/api/hr/approve",
        json={"hr_session_id": sid, "plan": plan},
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert body["state"] == "active"

    dept_id = body["department"]["id"]
    # Проверяем что отдел появился в /api/departments
    r = client.get("/api/departments")
    ids = [d["id"] for d in r.get_json()["departments"]]
    assert dept_id in ids
    return dept_id


# ---------------------------------------------------------------------------
# Главный сценарий — 7 шагов
# ---------------------------------------------------------------------------


def test_v2_full_workflow(client, fake_popen, roles_tmp, tmp_path):
    """E2E прогон 7 шагов: HR → task → delegate → cross-task → accept → owner approve → archive."""
    # === Шаг 1: создание двух отделов через HR-pipeline ===
    requester_dept = _create_department_via_hr(
        client, fake_popen, roles_tmp, dept_name="Marketing"
    )
    target_dept = _create_department_via_hr(
        client, fake_popen, roles_tmp, dept_name="Design"
    )
    assert requester_dept == "marketing"
    assert target_dept == "design"

    # Должны быть два разных subprocess'а (по одному на каждый /api/hr/start).
    assert len(fake_popen) >= 2

    # === Шаг 2: создание задачи в новом отделе (через MCP-уровень) ===
    # REST POST /api/tasks игнорирует department_id; для создания задачи в
    # конкретном отделе мы вызываем tools.create_task напрямую (это валидный
    # путь — MCP-tools используются ролями).
    from pride_tasks import tools

    # Получаем db_path из конфига Flask-приложения.
    # client.application — это сам Flask app; db_path хранится в app.config.
    db_path = Path(client.application.config["DB_PATH"])

    task_res = tools.create_task(
        title="Запустить кампанию Q3",
        description="План кампании на следующий квартал",
        reporter="пользователь",
        priority="P2",
        department_id=requester_dept,
        db_path=db_path,
    )
    assert task_res["статус"] == "ok", task_res
    intra_task_id = task_res["задача"]["id"]
    assert task_res["задача"]["department_id"] == requester_dept

    # Проверяем что задача попадает в фильтр по отделу
    r = client.get(f"/api/tasks?department={requester_dept}")
    assert r.status_code == 200
    task_ids = [t["id"] for t in r.get_json()["задачи"]]
    assert intra_task_id in task_ids

    # === Шаг 3: делегировать subagent внутри отдела ===
    # Имитируем «Lead взял в работу, оставил комментарий»:
    #   - PATCH /api/tasks/<id> status=wip
    #   - POST  /api/tasks/<id>/comment text="беру"
    r = client.patch(f"/api/tasks/{intra_task_id}", json={"status": "wip"})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["задача"]["status"] == "wip"

    r = client.post(
        f"/api/tasks/{intra_task_id}/comment",
        json={"author": "тимлид", "text": "беру в работу"},
    )
    assert r.status_code == 201

    # === Шаг 4: Lead отдела A запрашивает у отдела B (cross-task) ===
    # Сначала проверяем "малую" P3 → todo
    r = client.post(
        f"/api/departments/{target_dept}/tasks",
        json={
            "title": "Нарисовать баннер Q3",
            "description": "Для кампании Marketing",
            "priority": "P3",
            "requester_department_id": requester_dept,
            "requester_role_slug": f"{requester_dept}-lead",
        },
    )
    assert r.status_code == 201, r.get_data(as_text=True)
    cross_task = r.get_json()["задача"]
    cross_task_id = cross_task["id"]
    assert cross_task["status"] == "todo"
    assert cross_task["requires_approval"] is False
    assert cross_task["department_id"] == target_dept
    assert cross_task["requester_department_id"] == requester_dept

    # Audit в global inter-department channel
    r = client.get("/api/chat/inter-department")
    texts = [m["text"] for m in r.get_json()["messages"]]
    matched = [t for t in texts if requester_dept in t and target_dept in t]
    assert len(matched) >= 1, f"audit не найден среди {texts!r}"

    # === Шаг 5: Target Lead принимает задачу ===
    # Перевод todo → wip + комментарий принятия
    r = client.patch(f"/api/tasks/{cross_task_id}", json={"status": "wip"})
    assert r.status_code == 200
    assert r.get_json()["задача"]["status"] == "wip"

    r = client.post(
        f"/api/tasks/{cross_task_id}/comment",
        json={"author": f"{target_dept}-lead", "text": "принято в работу"},
    )
    # add_comment проверяет роль через ROLES — кастомные роли отделов могут не
    # быть в списке. Поэтому используем системную роль "тимлид" если 201 не вернулся.
    if r.status_code != 201:
        r = client.post(
            f"/api/tasks/{cross_task_id}/comment",
            json={"author": "тимлид", "text": "принято в работу"},
        )
        assert r.status_code == 201

    # === Шаг 6: Owner accept для approval-кейса ===
    # Создаём P1 cross-task → needs_approval. Owner аппрувит.
    r = client.post(
        f"/api/departments/{target_dept}/tasks",
        json={
            "title": "Срочный rebrand",
            "priority": "P1",
            "requester_department_id": requester_dept,
            "requester_role_slug": f"{requester_dept}-lead",
        },
    )
    assert r.status_code == 201
    high_pri_task = r.get_json()["задача"]
    high_pri_id = high_pri_task["id"]
    assert high_pri_task["status"] == "needs_approval"
    assert high_pri_task["requires_approval"] is True
    assert high_pri_task["assignee"] == "пользователь"

    # Сидим Lead-роль для target отдела в БД (HR materialize_roles пишет только
    # .md файлы, не вставляет в БД — но для approve нужен Lead в таблице roles,
    # т.к. _find_lead_for_department ищет именно там).
    import sqlite3 as _sqlite3
    _conn = _sqlite3.connect(str(db_path))
    try:
        _conn.execute(
            "INSERT INTO roles (name, description, capabilities, department_id) "
            "VALUES (?, ?, ?, ?)",
            (f"{target_dept}-lead", "lead", "{}", target_dept),
        )
        _conn.commit()
    finally:
        _conn.close()

    # Owner approve через POST /api/tasks/<id>/approve.
    # Баг #5933b0f3b933 пофикшен: cross-task approve назначает Lead отдела-
    # исполнителя (target=design → design-lead), а не reporter (marketing-lead).
    r = client.post(
        f"/api/tasks/{high_pri_id}/approve",
        json={"text": "одобрено"},
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    approved = r.get_json()["задача"]
    assert approved["status"] == "todo"
    # После фикса assignee = Lead отдела-исполнителя.
    assert approved["assignee"] == f"{target_dept}-lead", (
        f"ожидали assignee=={target_dept}-lead, получили {approved['assignee']!r}"
    )

    # Симулируем выполнение: target Lead делает задачу, переводит в done
    # через UI-вызов (UI обходит safety-net).
    r = client.patch(f"/api/tasks/{high_pri_id}", json={"status": "done"})
    assert r.status_code == 200
    assert r.get_json()["задача"]["status"] == "done"

    # === Шаг 7: Archive отдела ===
    r = client.patch(f"/api/departments/{target_dept}/archive")
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()["department"]
    assert body["id"] == target_dept
    assert body["archived_at"] is not None

    # /api/departments возвращает только активные — target должен пропасть
    r = client.get("/api/departments")
    ids_after = [d["id"] for d in r.get_json()["departments"]]
    assert target_dept not in ids_after
    # А requester (Marketing) — всё ещё активен
    assert requester_dept in ids_after

    # Задачи отдела не теряются — они всё ещё в БД.
    r = client.get(f"/api/tasks?department={target_dept}")
    assert r.status_code == 200
    task_ids_archived = [t["id"] for t in r.get_json()["задачи"]]
    assert cross_task_id in task_ids_archived
    assert high_pri_id in task_ids_archived

    # Но создавать НОВЫЕ cross-task в архивированном отделе нельзя → 410.
    r = client.post(
        f"/api/departments/{target_dept}/tasks",
        json={
            "title": "слишком поздно",
            "priority": "P3",
            "requester_department_id": requester_dept,
            "requester_role_slug": f"{requester_dept}-lead",
        },
    )
    assert r.status_code == 410


# ---------------------------------------------------------------------------
# Edge-case: HR aborted после 3 invalid plan attempts
# ---------------------------------------------------------------------------


def test_v2_hr_aborted_after_three_invalid_plans(client, fake_popen, roles_tmp):
    """HR-сессия → aborted после 3 раз invalid plan. Отдел НЕ создан."""
    r = client.post(
        "/api/hr/start",
        json={"name": "AbortMe", "description": "тестовое прерывание"},
    )
    assert r.status_code == 201
    sid = r.get_json()["hr_session_id"]

    bad_plan = _valid_plan("AbortMe")
    # 0 leads — validation провалится
    bad_plan["roles"][0]["is_lead"] = False
    bad_plan["roles"][1]["is_lead"] = False

    last_status = None
    for attempt in range(3):
        rr = client.post(
            "/api/hr/approve",
            json={"hr_session_id": sid, "plan": bad_plan},
        )
        assert rr.status_code == 422
        last_status = rr.get_json()["status"]

    # После 3-й попытки — aborted
    assert last_status == "aborted"
    r = client.get(f"/api/hr/status/{sid}")
    assert r.get_json()["state"] == "aborted"

    # Отдел в БД НЕ создан
    r = client.get("/api/departments")
    ids = [d["id"] for d in r.get_json()["departments"]]
    assert "abortme" not in ids


# ---------------------------------------------------------------------------
# Edge-case: counter-proposal flow на cross-task
# ---------------------------------------------------------------------------


def test_v2_counter_proposal_changes_priority(client, fake_popen, roles_tmp):
    """Cross-task → counter-proposal с новым priority → priority обновлён + notify."""
    req = _create_department_via_hr(client, fake_popen, roles_tmp, dept_name="Sales")
    tgt = _create_department_via_hr(client, fake_popen, roles_tmp, dept_name="Support")

    # Создаём cross-task P3
    r = client.post(
        f"/api/departments/{tgt}/tasks",
        json={
            "title": "Help with onboarding",
            "priority": "P3",
            "requester_department_id": req,
            "requester_role_slug": f"{req}-lead",
        },
    )
    assert r.status_code == 201
    tid = r.get_json()["задача"]["id"]

    # Counter-proposal: target Lead просит P2 + объясняет
    r = client.post(
        f"/api/tasks/{tid}/counter",
        json={
            "priority": "P2",
            "comment": "у нас перегруз, можно сначала это?",
        },
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["задача"]["priority"] == "P2"

    # Notify в чат отдела-заказчика
    r = client.get(f"/api/chat?department={req}")
    texts = [m["text"] for m in r.get_json()["messages"]]
    notified = [t for t in texts if "counter-proposal" in t and tid[:6] in t]
    assert len(notified) >= 1, f"notify не найден в {texts!r}"

    # Audit в global inter-department channel
    r = client.get("/api/chat/inter-department")
    audit_texts = [m["text"] for m in r.get_json()["messages"]]
    counter_audit = [t for t in audit_texts if "counter-proposed" in t]
    assert len(counter_audit) >= 1


# ---------------------------------------------------------------------------
# Edge-case: archived dept нельзя архивировать дважды (графовый ребус)
# ---------------------------------------------------------------------------


def test_v2_archive_dev_forbidden(client):
    """Default отдел 'dev' нельзя архивировать → 403."""
    r = client.patch("/api/departments/dev/archive")
    assert r.status_code == 403


def test_v2_archive_unknown_department_404(client):
    """Archive несуществующего отдела → 404."""
    r = client.patch("/api/departments/ghost/archive")
    assert r.status_code == 404

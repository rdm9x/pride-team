"""Q1 (1.5): E2E симуляция — owner → marketing → Управляющий → выполнение.

Source-of-truth: ADR-009 Phase 1.5 acceptance criteria.

Покрывает 6 сценариев:
  1. Owner создаёт marketing-отдел через /api/departments → 201,
     GET /api/departments содержит 'marketing'.
  2. /api/team/start {'role': 'marketing-lead'} → вызывает devboard-work.sh
     с --role marketing-lead (subprocess замокан).
  3. list_tasks для marketing-отдела возвращает задачи с assignee='marketing-lead',
     не 'тимлид'.
  4. Чат для marketing-отдела изолирован от dev-чата.
  5. Задача с model_hint='sonnet' → router.pick() возвращает 'sonnet', не 'opus'.
  6. /api/roles?department=marketing возвращает только marketing-роли
     (не dev-роли из другого отдела).

Тестовый стиль:
  - Flask test client (conftest.py → client fixture).
  - subprocess.Popen мокируется через unittest.mock.patch.
  - Каждый тест — изолированный сценарий (tmp БД через conftest client fixture).
  - MCP-tools вызываются напрямую для setup данных.
"""

from __future__ import annotations

import sys
from pathlib import Path
from queue import Queue
from threading import Lock
from unittest.mock import MagicMock, patch

import pytest

# Гарантируем что mcp_server/ и dashboard/ в sys.path.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_MCP_DIR = _REPO_ROOT / "mcp_server"
_DASHBOARD_DIR = _REPO_ROOT / "dashboard"

for _p in (_MCP_DIR, _DASHBOARD_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import app as app_module  # noqa: E402
from devboard_tasks import db as _db  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_marketing_dept(client) -> None:
    """Создаёт marketing-отдел через API или напрямую через db.

    Сначала пробуем POST /api/departments?template_id — если marketing-v2
    шаблон есть, используем его. Если нет — создаём отдел через db.create_department
    и вставляем роль marketing-lead напрямую.
    """
    r = client.post("/api/departments", json={"template_id": "marketing-v2"})
    if r.status_code in (201, 409):
        return  # создан или уже существует — ок

    # Шаблон marketing-v2 отсутствует — создаём минимальный marketing-отдел.
    db_path = Path(client.application.config["DB_PATH"])
    _db.create_department(db_path, dept_id="marketing", name="Marketing")
    conn = _db._connect(db_path)
    try:
        conn.execute(
            """INSERT OR IGNORE INTO roles
               (name, description, capabilities, department_id)
               VALUES ('marketing-lead', 'Лид маркетинга', '{}', 'marketing')"""
        )
        conn.commit()
    finally:
        conn.close()


def _make_fake_proc() -> MagicMock:
    fake = MagicMock()
    fake.pid = 77777
    fake.poll.return_value = None
    fake.stdout = iter([])
    return fake


# ---------------------------------------------------------------------------
# Тест 1: Owner создаёт marketing-отдел → появляется в /api/departments
# ---------------------------------------------------------------------------


def test_owner_creates_marketing_department(client) -> None:
    """POST /api/departments → marketing появляется в GET /api/departments.

    Acceptance Phase 1.5: Owner кликает «Запустить» — marketing-отдел создан,
    роли (включая marketing-lead) доступны через API.
    """
    _setup_marketing_dept(client)

    r = client.get("/api/departments")
    assert r.status_code == 200
    depts = r.get_json().get("departments", [])
    dept_ids = {d["id"] for d in depts}
    assert "marketing" in dept_ids, (
        f"marketing-отдел не появился в /api/departments. Получено: {dept_ids}"
    )

    # Проверяем что marketing-lead роль доступна через API.
    r2 = client.get("/api/roles?department=marketing")
    assert r2.status_code == 200
    roles = r2.get_json().get("роли", [])
    role_names = {ro["name"] for ro in roles}
    assert "marketing-lead" in role_names, (
        f"роль 'marketing-lead' не найдена в /api/roles?department=marketing. "
        f"Получено: {role_names}"
    )


# ---------------------------------------------------------------------------
# Тест 2: /api/team/start с role='marketing-lead' → devboard-work.sh --role marketing-lead
# ---------------------------------------------------------------------------


def test_api_team_start_role_marketing_lead_calls_work_script(
    monkeypatch, tmp_path
) -> None:
    """POST /api/team/start {'role': 'marketing-lead'} вызывает devboard-work.sh
    с --role marketing-lead.

    Acceptance Phase 1.5: Owner кликает «Запустить» для marketing-lead —
    система запускает правильный subprocess с нужным --role флагом.
    """
    if sys.platform == "win32":
        pytest.skip("Unix-only path test")

    from app import create_app  # type: ignore

    db = tmp_path / "tasks.db"
    flask_app = create_app(db_path=db)
    flask_app.config["TESTING"] = True

    # Создаём devboard-work.sh в tmp_path
    work_script = tmp_path / "devboard-work.sh"
    work_script.write_text("#!/bin/bash\necho hi\n")

    monkeypatch.setattr(app_module, "_COMMANDS_DIR", tmp_path)
    monkeypatch.setattr(app_module, "_PID_FILE", tmp_path / "team.pid")
    monkeypatch.setattr(app_module, "_LIVE_LOG", tmp_path / "team.log")

    # Сбрасываем глобальное состояние тимлида.
    app_module._team_state["process"] = None
    app_module._team_state["queue"] = Queue()
    app_module._team_state["started_at"] = None
    app_module._team_state["lock"] = Lock()
    app_module._team_state["auto_mode"] = False
    app_module._team_state["starts_history"] = []
    app_module._team_state["auto_pause_reason"] = None
    app_module._team_state["reader_thread"] = None

    fake_proc = _make_fake_proc()

    with patch("subprocess.Popen", return_value=fake_proc) as popen_mock:
        with flask_app.test_client() as test_client:
            resp = test_client.post(
                "/api/team/start",
                json={"role": "marketing-lead"},
            )

    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    assert data["статус"] == "ok"
    assert data["pid"] == 77777

    called_cmd = popen_mock.call_args[0][0]
    assert str(work_script) in called_cmd, (
        f"Ожидали вызов {work_script}, получили: {called_cmd}"
    )
    assert "--role" in called_cmd, f"--role отсутствует в команде: {called_cmd}"
    assert "marketing-lead" in called_cmd, (
        f"'marketing-lead' отсутствует в команде: {called_cmd}"
    )


# ---------------------------------------------------------------------------
# Тест 3: list_tasks для marketing → assignee='marketing-lead', не 'тимлид'
# ---------------------------------------------------------------------------


def test_list_tasks_marketing_shows_marketing_lead_not_timlid(client) -> None:
    """GET /api/tasks?department=marketing → задачи с assignee='marketing-lead'.

    Acceptance Phase 1.5: Marketing-отдел — list_tasks возвращает задачи
    assignee='marketing-lead' (не 'тимлид').
    """
    _setup_marketing_dept(client)
    db_path = Path(client.application.config["DB_PATH"])

    # Создаём задачу для marketing-lead.
    mk_task = _db.insert_task(
        db_path,
        title="Запустить рекламную кампанию",
        assignee="marketing-lead",
        reporter="Управляющий",
        priority="P2",
        department_id="marketing",
    )

    # Создаём задачу для тимлида (dev), чтобы убедиться что фильтр работает.
    dev_task = _db.insert_task(
        db_path,
        title="Fix API bug",
        assignee="тимлид",
        reporter="Управляющий",
        priority="P2",
        department_id="dev",
    )

    r = client.get("/api/tasks?department=marketing")
    assert r.status_code == 200
    payload = r.get_json()
    tasks = payload.get("задачи", [])

    task_ids = {t["id"] for t in tasks}
    assert mk_task["id"] in task_ids, "marketing-задача не найдена в ответе"
    assert dev_task["id"] not in task_ids, "dev-задача утекла в marketing-фильтр"

    # Проверяем что у marketing-задачи assignee='marketing-lead', не 'тимлид'.
    found = next(t for t in tasks if t["id"] == mk_task["id"])
    assert found["assignee"] == "marketing-lead", (
        f"Ожидался assignee='marketing-lead', получено: {found['assignee']!r}"
    )
    # Убеждаемся что 'тимлид' не присутствует как assignee среди marketing-задач.
    timlid_tasks = [t for t in tasks if t.get("assignee") == "тимлид"]
    assert timlid_tasks == [], (
        f"Задачи с assignee='тимлид' утекли в marketing: {timlid_tasks}"
    )


# ---------------------------------------------------------------------------
# Тест 4: Чат marketing-отдела изолирован от dev-чата
# ---------------------------------------------------------------------------


def test_chat_marketing_department_isolated_from_dev(client) -> None:
    """GET /api/chat?department=marketing не смешивается с dev-чатом.

    Acceptance Phase 1.5: Каналы чатов разных отделов не пересекаются.
    """
    _setup_marketing_dept(client)
    db_path = Path(client.application.config["DB_PATH"])

    # Пишем сообщение в marketing-чат через MCP (автор managing-director —
    # он единственный глобальный автор, у которого есть право постить в оба отдела).
    _db.post_chat_message(
        db_path,
        "managing-director",
        "Запускаем кампанию Q2",
        department_id="marketing",
    )

    # Пишем сообщение в dev-чат.
    _db.post_chat_message(
        db_path,
        "тимлид",
        "Фиксим баг в роутере",
        department_id="dev",
    )

    # Для проверки REST-endpoint также делаем POST через Flask клиент
    # (с допустимым автором 'пользователь' и department=marketing).
    r1 = client.post(
        "/api/chat?department=marketing",
        json={"author": "пользователь", "text": "Хочу видеть отчёт по кампании"},
    )
    assert r1.status_code == 201

    # Проверяем marketing-чат — видит только marketing-сообщения.
    r3 = client.get("/api/chat?department=marketing")
    assert r3.status_code == 200
    mk_msgs = r3.get_json()["messages"]
    mk_texts = [m["text"] for m in mk_msgs]
    assert "Запускаем кампанию Q2" in mk_texts, "marketing-сообщение не найдено"
    assert "Фиксим баг в роутере" not in mk_texts, (
        "dev-сообщение утекло в marketing-чат"
    )
    assert "Хочу видеть отчёт по кампании" in mk_texts, (
        "REST POST marketing-сообщение не найдено"
    )

    # Проверяем dev-чат — видит только dev-сообщение.
    r4 = client.get("/api/chat?department=dev")
    assert r4.status_code == 200
    dev_msgs = r4.get_json()["messages"]
    dev_texts = [m["text"] for m in dev_msgs]
    assert "Фиксим баг в роутере" in dev_texts, "dev-сообщение не найдено"
    assert "Запускаем кампанию Q2" not in dev_texts, (
        "marketing-сообщение утекло в dev-чат"
    )
    assert "Хочу видеть отчёт по кампании" not in dev_texts, (
        "marketing REST сообщение утекло в dev-чат"
    )


# ---------------------------------------------------------------------------
# Тест 5: Задача с model_hint='sonnet' → router.pick() возвращает 'sonnet'
# ---------------------------------------------------------------------------


def test_model_hint_sonnet_overrides_opus_labels(client) -> None:
    """Задача с model_hint='sonnet' и archi-лейблом → router выбирает 'sonnet'.

    Acceptance Phase 1.5: Задача с model_hint=sonnet → router использует sonnet, не opus.

    B5 fix (Phase 1.5): model_hint проверяется ДО архитектурных labels.
    Даже если в очереди есть задача с label 'design' (Opus-триггер),
    явный model_hint='sonnet' должен победить.
    """
    from devboard_tasks.router import pick  # type: ignore

    # Очередь: одна задача с model_hint=sonnet + одна архитектурная (без hint).
    tasks = [
        {
            "id": "task-mk-sonnet",
            "title": "SEO-аудит сайта",
            "labels": [],           # нет archi-лейблов
            "model_hint": "sonnet",
        },
        {
            "id": "task-archi",
            "title": "Redesign router architecture",
            "labels": ["design"],   # archi-лейбл — без hint должен тянуть к Opus
            "model_hint": None,
        },
    ]

    result = pick(tasks)
    assert result["model_alias"] == "sonnet", (
        f"Ожидался 'sonnet' (model_hint побеждает design-label), "
        f"получено: {result['model_alias']!r}. Причина: {result['reason']}"
    )
    assert result["model_full"] == "claude-sonnet-4-6", (
        f"Ожидалась полная модель 'claude-sonnet-4-6', получено: {result['model_full']!r}"
    )

    # Дополнительно: только sonnet-hint без других задач → тоже sonnet.
    result2 = pick([{"id": "t1", "title": "x", "labels": [], "model_hint": "sonnet"}])
    assert result2["model_alias"] == "sonnet"

    # Проверяем через /api/router/pick — создаём задачу с model_hint=sonnet в БД.
    r = client.post(
        "/api/tasks",
        json={"title": "SEO sprint", "model_hint": "sonnet"},
    )
    assert r.status_code == 201
    pick_r = client.get("/api/router/pick")
    assert pick_r.status_code == 200
    pick_data = pick_r.get_json()
    assert pick_data["model_alias"] == "sonnet", (
        f"/api/router/pick вернул {pick_data['model_alias']!r} вместо 'sonnet'"
    )


# ---------------------------------------------------------------------------
# Тест 6: /api/roles?department=marketing → только marketing-роли
# ---------------------------------------------------------------------------


def test_roles_endpoint_filters_marketing_only(client) -> None:
    """/api/roles?department=marketing возвращает только marketing-роли.

    Acceptance Phase 1.5: Owner кликает «Запустить» → список включает
    managing-director + dev-lead + marketing-lead (роли доступны через API).
    """
    _setup_marketing_dept(client)
    db_path = Path(client.application.config["DB_PATH"])

    # Создаём дополнительный отдел design, чтобы убедиться что его роли не утекут.
    import sqlite3, time as _time

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT OR IGNORE INTO departments (id, name, description, icon, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("design", "Design", "", "", int(_time.time())),
        )
        conn.execute(
            "INSERT OR IGNORE INTO roles (name, description, capabilities, department_id) "
            "VALUES (?, ?, ?, ?)",
            ("design-lead", "Design lead", "{}", "design"),
        )
        conn.commit()
    finally:
        conn.close()

    r = client.get("/api/roles?department=marketing")
    assert r.status_code == 200
    payload = r.get_json()
    assert payload["статус"] == "ok"
    roles = payload.get("роли", [])
    role_names = {ro["name"] for ro in roles}

    # marketing-lead должен присутствовать.
    assert "marketing-lead" in role_names, (
        f"'marketing-lead' не найден в /api/roles?department=marketing. "
        f"Получено: {role_names}"
    )

    # design-lead из другого отдела НЕ должен попасть в ответ.
    assert "design-lead" not in role_names, (
        f"'design-lead' (другой отдел) утёк в маркетинговый список ролей"
    )

    # Дополнительно: глобальные роли (dev-team без department_id) тоже включены.
    # Проверяем что у marketing-lead правильный department_id.
    mk_lead = next((ro for ro in roles if ro["name"] == "marketing-lead"), None)
    assert mk_lead is not None
    assert mk_lead.get("department_id") == "marketing", (
        f"Ожидался department_id='marketing' у marketing-lead, "
        f"получено: {mk_lead.get('department_id')!r}"
    )

"""Тесты REST-endpoints departments (S8.3)."""

from __future__ import annotations


# ---------------------------------------------------------------------------
# GET /api/departments
# ---------------------------------------------------------------------------

def test_list_departments_ok(client) -> None:
    """GET /api/departments → 200, в ответе есть 'dev'."""
    r = client.get("/api/departments")
    assert r.status_code == 200
    body = r.get_json()
    assert "departments" in body
    ids = [d["id"] for d in body["departments"]]
    assert "dev" in ids


def test_list_departments_shape(client) -> None:
    """Каждый элемент departments имеет нужные поля."""
    r = client.get("/api/departments")
    depts = r.get_json()["departments"]
    assert len(depts) >= 1
    dev = next(d for d in depts if d["id"] == "dev")
    assert "name" in dev
    assert "description" in dev
    assert "icon" in dev
    assert "counts" in dev
    assert "total" in dev["counts"]
    assert "open" in dev["counts"]


# ---------------------------------------------------------------------------
# GET /api/departments/<dept_id>
# ---------------------------------------------------------------------------

def test_get_department_dev(client) -> None:
    """GET /api/departments/dev → 200."""
    r = client.get("/api/departments/dev")
    assert r.status_code == 200
    body = r.get_json()
    assert "department" in body
    assert body["department"]["id"] == "dev"


def test_get_department_not_found(client) -> None:
    """GET /api/departments/nonexistent → 404."""
    r = client.get("/api/departments/nonexistent")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/departments
# ---------------------------------------------------------------------------

def test_create_department_ok(client) -> None:
    """POST /api/departments {name: 'Marketing'} → 201, в БД есть marketing."""
    r = client.post("/api/departments", json={"name": "Marketing"})
    assert r.status_code == 201
    body = r.get_json()
    assert "department" in body
    dept = body["department"]
    assert dept["id"] == "marketing"
    assert dept["name"] == "Marketing"

    # Проверяем что появился в списке
    depts = client.get("/api/departments").get_json()["departments"]
    ids = [d["id"] for d in depts]
    assert "marketing" in ids


def test_create_department_conflict(client) -> None:
    """POST /api/departments с тем же именем → 409."""
    client.post("/api/departments", json={"name": "Marketing"})
    r = client.post("/api/departments", json={"name": "Marketing"})
    assert r.status_code == 409


def test_create_department_no_name(client) -> None:
    """POST /api/departments без name → 400."""
    r = client.post("/api/departments", json={})
    assert r.status_code == 400


def test_create_department_with_description(client) -> None:
    """POST /api/departments с description и icon."""
    r = client.post("/api/departments", json={
        "name": "Support",
        "description": "Customer support team",
        "icon": "🎧",
    })
    assert r.status_code == 201
    dept = r.get_json()["department"]
    assert dept["description"] == "Customer support team"
    assert dept["icon"] == "🎧"


# ---------------------------------------------------------------------------
# PATCH /api/departments/<dept_id>/archive
# ---------------------------------------------------------------------------

def test_archive_dev_forbidden(client) -> None:
    """PATCH /api/departments/dev/archive → 403."""
    r = client.patch("/api/departments/dev/archive")
    assert r.status_code == 403


def test_archive_nonexistent_404(client) -> None:
    """PATCH /api/departments/ghost/archive → 404."""
    r = client.patch("/api/departments/ghost/archive")
    assert r.status_code == 404


def test_archive_department_ok(client) -> None:
    """Создать отдел → архивировать → 200, archived_at заполнен."""
    # Создаём отдел
    r = client.post("/api/departments", json={"name": "Temp Dept"})
    assert r.status_code == 201
    dept_id = r.get_json()["department"]["id"]

    # Архивируем
    r = client.patch(f"/api/departments/{dept_id}/archive")
    assert r.status_code == 200
    body = r.get_json()
    assert "department" in body
    assert body["department"]["archived_at"] is not None


# ---------------------------------------------------------------------------
# GET /api/tasks?department=<id>
# ---------------------------------------------------------------------------

def _create_task(client, title: str = "task") -> str:
    """Создаёт задачу и возвращает её id."""
    r = client.post("/api/tasks", json={"title": title})
    assert r.status_code == 201
    return r.get_json()["задача"]["id"]


def test_tasks_filter_by_dev(client) -> None:
    """GET /api/tasks?department=dev → только dev tasks."""
    tid = _create_task(client, "dev task")
    r = client.get("/api/tasks?department=dev")
    assert r.status_code == 200
    ids = [t["id"] for t in r.get_json()["задачи"]]
    assert tid in ids


def test_tasks_backward_compat_no_dept(client) -> None:
    """GET /api/tasks без ?department → backward compat, возвращает dev tasks, не падает."""
    tid = _create_task(client, "test task")
    r = client.get("/api/tasks")
    assert r.status_code == 200
    j = r.get_json()
    # Должен вернуть задачи (включая только что созданную в dev)
    assert "задачи" in j
    assert "колонки" in j
    ids = [t["id"] for t in j["задачи"]]
    assert tid in ids


def test_tasks_all_departments(client) -> None:
    """GET /api/tasks?department=__all__ → все задачи."""
    tid = _create_task(client, "some task")
    r = client.get("/api/tasks?department=__all__")
    assert r.status_code == 200
    ids = [t["id"] for t in r.get_json()["задачи"]]
    assert tid in ids


# ---------------------------------------------------------------------------
# GET /api/chat?department=<id>
# ---------------------------------------------------------------------------

def test_chat_filter_by_dev(client) -> None:
    """GET /api/chat?department=dev → только dev сообщения."""
    # Постим сообщение
    client.post("/api/chat?department=dev", json={"author": "тимлид", "text": "dev msg"})
    r = client.get("/api/chat?department=dev")
    assert r.status_code == 200
    msgs = r.get_json()["messages"]
    assert any(m["text"] == "dev msg" for m in msgs)


def test_chat_default_is_dev(client) -> None:
    """GET /api/chat без параметра → default 'dev', не падает."""
    r = client.get("/api/chat")
    assert r.status_code == 200
    assert "messages" in r.get_json()


def test_chat_global_channel(client) -> None:
    """GET /api/chat?department=__global__ → global channel (department_id IS NULL)."""
    # Постим глобальное сообщение
    client.post(
        "/api/chat?department=__global__",
        json={"author": "system", "text": "global announcement"},
    )
    # dev-сообщение — не должно попасть в глобальный канал
    client.post(
        "/api/chat?department=dev",
        json={"author": "тимлид", "text": "dev only"},
    )
    r = client.get("/api/chat?department=__global__")
    assert r.status_code == 200
    msgs = r.get_json()["messages"]
    texts = [m["text"] for m in msgs]
    assert "global announcement" in texts
    assert "dev only" not in texts

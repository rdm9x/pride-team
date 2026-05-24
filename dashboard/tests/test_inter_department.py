"""Тесты inter-department workflow (S11.1, ADR-005).

Покрывает:
  - POST /api/departments/<target>/tasks: happy path P3 → todo, P1/P2 → needs_approval,
    destructive label → needs_approval, AuthZ Lead/owner, 404 target, 410 archived,
    backward compat (старые /api/tasks без новых полей).
  - GET /api/chat/inter-department: глобальный канал, audit-сообщения.
  - POST /api/tasks/<id>/counter: counter-proposal обновляет priority, пишет историю,
    шлёт notify в чат отдела-заказчика.
  - GET /api/departments/<id>?task_id=...: queue_position в ответе.
  - GET /api/departments/<id>/queue-position?priority=...: preview позиции.
"""

from __future__ import annotations


# Helper -----------------------------------------------------------------

def _create_dept(client, name: str) -> str:
    r = client.post("/api/departments", json={"name": name})
    assert r.status_code == 201, r.get_data(as_text=True)
    return r.get_json()["department"]["id"]


# ---------------------------------------------------------------------------
# POST /api/departments/<target>/tasks
# ---------------------------------------------------------------------------

def test_inter_dept_create_p3_goes_to_todo(client) -> None:
    """P3 inter-dept task → status=todo, requires_approval=false, audit в global chat."""
    target = _create_dept(client, "Design")
    requester = _create_dept(client, "Marketing")
    r = client.post(
        f"/api/departments/{target}/tasks",
        json={
            "title": "draw banner",
            "description": "for Q3 launch",
            "priority": "P3",
            "requester_department_id": requester,
            "requester_role_slug": f"{requester}-lead",
        },
    )
    assert r.status_code == 201, r.get_data(as_text=True)
    task = r.get_json()["задача"]
    assert task["status"] == "todo"
    assert task["requires_approval"] is False
    assert task["priority"] == "P3"
    assert task["department_id"] == target
    assert task["requester_department_id"] == requester
    assert task["requester_role_slug"] == f"{requester}-lead"


def test_inter_dept_create_p1_needs_approval(client) -> None:
    """P1 inter-dept → needs_approval, requires_approval=True, assignee=пользователь."""
    target = _create_dept(client, "Design")
    requester = _create_dept(client, "Marketing")
    r = client.post(
        f"/api/departments/{target}/tasks",
        json={
            "title": "rebrand all banners",
            "priority": "P1",
            "requester_department_id": requester,
            "requester_role_slug": f"{requester}-lead",
        },
    )
    assert r.status_code == 201
    task = r.get_json()["задача"]
    assert task["status"] == "needs_approval"
    assert task["requires_approval"] is True
    assert task["assignee"] == "пользователь"


def test_inter_dept_destructive_label_needs_approval(client) -> None:
    """Label 'destructive' даже на P3 → needs_approval."""
    target = _create_dept(client, "Design")
    requester = _create_dept(client, "Marketing")
    r = client.post(
        f"/api/departments/{target}/tasks",
        json={
            "title": "purge old assets",
            "priority": "P3",
            "labels": ["destructive", "cleanup"],
            "requester_department_id": requester,
            "requester_role_slug": f"{requester}-lead",
        },
    )
    assert r.status_code == 201
    task = r.get_json()["задача"]
    assert task["status"] == "needs_approval"
    assert task["requires_approval"] is True


def test_inter_dept_authz_403_for_non_lead(client) -> None:
    """requester_role_slug не Lead отдела A → 403."""
    target = _create_dept(client, "Design")
    requester = _create_dept(client, "Marketing")
    r = client.post(
        f"/api/departments/{target}/tasks",
        json={
            "title": "draw banner",
            "requester_department_id": requester,
            # roleslug не Lead отдела marketing — обычный copywriter
            "requester_role_slug": "marketing-copywriter",
        },
    )
    assert r.status_code == 403, r.get_data(as_text=True)
    body = r.get_json()
    assert body.get("your_role") == "marketing-copywriter"


def test_inter_dept_target_not_found_404(client) -> None:
    """Target отдел не существует → 404."""
    requester = _create_dept(client, "Marketing")
    r = client.post(
        "/api/departments/ghost/tasks",
        json={
            "title": "x",
            "requester_department_id": requester,
            "requester_role_slug": f"{requester}-lead",
        },
    )
    assert r.status_code == 404


def test_inter_dept_archived_target_410(client) -> None:
    """Target архивирован → 410 Gone."""
    target = _create_dept(client, "Legacy X")
    requester = _create_dept(client, "Marketing")
    # Архивируем target
    r = client.patch(f"/api/departments/{target}/archive")
    assert r.status_code == 200
    # Пробуем создать cross-task
    r = client.post(
        f"/api/departments/{target}/tasks",
        json={
            "title": "x",
            "requester_department_id": requester,
            "requester_role_slug": f"{requester}-lead",
        },
    )
    assert r.status_code == 410, r.get_data(as_text=True)


def test_inter_dept_missing_title_400(client) -> None:
    """title обязателен → 400."""
    target = _create_dept(client, "Design")
    requester = _create_dept(client, "Marketing")
    r = client.post(
        f"/api/departments/{target}/tasks",
        json={
            "requester_department_id": requester,
            "requester_role_slug": f"{requester}-lead",
        },
    )
    assert r.status_code == 400


def test_inter_dept_owner_role_accepted(client) -> None:
    """requester_role_slug='owner' принимается (admin override)."""
    target = _create_dept(client, "Design")
    requester = _create_dept(client, "Marketing")
    r = client.post(
        f"/api/departments/{target}/tasks",
        json={
            "title": "owner forcing",
            "priority": "P3",
            "requester_department_id": requester,
            "requester_role_slug": "owner",
        },
    )
    assert r.status_code == 201, r.get_data(as_text=True)


def test_inter_dept_dev_legacy_тимлид_accepted(client) -> None:
    """Для отдела 'dev' (legacy) role_slug='тимлид' — валидный Lead."""
    target = _create_dept(client, "Design")
    r = client.post(
        f"/api/departments/{target}/tasks",
        json={
            "title": "legacy ask",
            "priority": "P3",
            "requester_department_id": "dev",
            "requester_role_slug": "тимлид",
        },
    )
    assert r.status_code == 201, r.get_data(as_text=True)
    task = r.get_json()["задача"]
    assert task["requester_department_id"] == "dev"


# ---------------------------------------------------------------------------
# Backward compat: старые /api/tasks работают без новых колонок
# ---------------------------------------------------------------------------

def test_old_api_tasks_no_inter_dept_fields(client) -> None:
    """POST /api/tasks без inter-dept полей — задача создаётся, requester_*=None."""
    r = client.post("/api/tasks", json={"title": "regular task"})
    assert r.status_code == 201
    task = r.get_json()["задача"]
    assert task.get("requester_department_id") is None
    assert task.get("requester_role_slug") is None


# ---------------------------------------------------------------------------
# GET /api/chat/inter-department
# ---------------------------------------------------------------------------

def test_inter_dept_audit_appears_in_global_channel(client) -> None:
    """После создания inter-task — audit-сообщение в /api/chat/inter-department."""
    target = _create_dept(client, "Design")
    requester = _create_dept(client, "Marketing")
    client.post(
        f"/api/departments/{target}/tasks",
        json={
            "title": "draw banner",
            "priority": "P3",
            "requester_department_id": requester,
            "requester_role_slug": f"{requester}-lead",
        },
    )
    r = client.get("/api/chat/inter-department")
    assert r.status_code == 200
    msgs = r.get_json()["messages"]
    # Должно быть как минимум одно audit-сообщение, содержащее оба отдела
    texts = [m["text"] for m in msgs]
    matched = [t for t in texts if requester in t and target in t]
    assert len(matched) >= 1, f"audit не найден среди {texts!r}"
    # И все эти сообщения должны быть с department_id IS NULL (глобальные)
    for m in msgs:
        assert m["department_id"] is None


def test_inter_dept_chat_isolated_from_dev(client) -> None:
    """Сообщения из /api/chat (dev) не пересекаются с inter-department."""
    # Постим dev-сообщение
    client.post("/api/chat?department=dev", json={"author": "тимлид", "text": "dev only msg"})
    r = client.get("/api/chat/inter-department")
    texts = [m["text"] for m in r.get_json()["messages"]]
    assert "dev only msg" not in texts


# ---------------------------------------------------------------------------
# POST /api/tasks/<id>/counter
# ---------------------------------------------------------------------------

def _create_inter_task(client, *, priority: str = "P3") -> tuple[str, str, str]:
    """Создаёт inter-task и возвращает (task_id, requester_dept, target_dept)."""
    target = _create_dept(client, "Design")
    requester = _create_dept(client, "Marketing")
    r = client.post(
        f"/api/departments/{target}/tasks",
        json={
            "title": "draw banner",
            "priority": priority,
            "requester_department_id": requester,
            "requester_role_slug": f"{requester}-lead",
        },
    )
    assert r.status_code == 201
    return r.get_json()["задача"]["id"], requester, target


def test_counter_proposal_updates_priority(client) -> None:
    """Counter-proposal с priority меняет приоритет задачи."""
    tid, req, tgt = _create_inter_task(client, priority="P3")
    r = client.post(
        f"/api/tasks/{tid}/counter",
        json={"priority": "P2", "comment": "сначала вот это, потом ваше"},
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert body["задача"]["priority"] == "P2"


def test_counter_proposal_requires_comment(client) -> None:
    """Counter без comment → 400."""
    tid, _, _ = _create_inter_task(client)
    r = client.post(f"/api/tasks/{tid}/counter", json={"priority": "P2"})
    assert r.status_code == 400


def test_counter_proposal_not_inter_dept_400(client) -> None:
    """Counter на не-inter задаче → 400."""
    # обычная задача без requester_department_id
    r = client.post("/api/tasks", json={"title": "intra"})
    tid = r.get_json()["задача"]["id"]
    r = client.post(f"/api/tasks/{tid}/counter", json={"comment": "x"})
    assert r.status_code == 400


def test_counter_proposal_writes_history(client) -> None:
    """Counter оставляет комментарий в истории задачи (author=system)."""
    tid, _, _ = _create_inter_task(client)
    client.post(
        f"/api/tasks/{tid}/counter",
        json={"priority": "P2", "comment": "capacity issue"},
    )
    # Читаем задачу с историей
    r = client.get(f"/api/tasks/{tid}")
    body = r.get_json()
    comments = body["задача"]["comments"]
    counter_comments = [
        c for c in comments
        if c["author"] == "system" and "counter-proposal" in c["text"]
    ]
    assert len(counter_comments) >= 1
    assert "capacity issue" in counter_comments[0]["text"]


def test_counter_proposal_notifies_origin(client) -> None:
    """После counter-а в чат отдела-заказчика пишется notify."""
    tid, req, tgt = _create_inter_task(client)
    client.post(
        f"/api/tasks/{tid}/counter",
        json={"comment": "let's discuss"},
    )
    # Чат отдела-заказчика
    r = client.get(f"/api/chat?department={req}")
    texts = [m["text"] for m in r.get_json()["messages"]]
    notified = [t for t in texts if "counter-proposal" in t and tid[:6] in t]
    assert len(notified) >= 1, f"notify не найден в {texts!r}"


def test_counter_proposal_404_for_missing_task(client) -> None:
    """Counter на несуществующую задачу → 404."""
    r = client.post("/api/tasks/notexist00/counter", json={"comment": "x"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Capacity hint: GET /api/departments/<id>?task_id=...
# ---------------------------------------------------------------------------

def test_department_queue_position_for_task(client) -> None:
    """GET /api/departments/<id>?task_id=<tid> → queue_position и queue_total в ответе."""
    target = _create_dept(client, "Design")
    requester = _create_dept(client, "Marketing")
    # Создаём 2 задачи в target напрямую (cross-task)
    r1 = client.post(
        f"/api/departments/{target}/tasks",
        json={
            "title": "task A",
            "priority": "P3",
            "requester_department_id": requester,
            "requester_role_slug": f"{requester}-lead",
        },
    )
    r2 = client.post(
        f"/api/departments/{target}/tasks",
        json={
            "title": "task B",
            "priority": "P3",
            "requester_department_id": requester,
            "requester_role_slug": f"{requester}-lead",
        },
    )
    tid_a = r1.get_json()["задача"]["id"]
    tid_b = r2.get_json()["задача"]["id"]
    # Позиция A
    r = client.get(f"/api/departments/{target}?task_id={tid_a}")
    body = r.get_json()["department"]
    assert body["queue_position"] == 1
    assert body["queue_total"] >= 2
    # Позиция B — больше A (later created_at)
    r = client.get(f"/api/departments/{target}?task_id={tid_b}")
    body = r.get_json()["department"]
    assert body["queue_position"] >= 2


def test_department_queue_position_higher_priority_first(client) -> None:
    """P1 задача обгоняет P3 задачи в очереди."""
    target = _create_dept(client, "Design")
    requester = _create_dept(client, "Marketing")
    # Сначала P3
    r_p3 = client.post(
        f"/api/departments/{target}/tasks",
        json={
            "title": "low pri",
            "priority": "P3",
            "requester_department_id": requester,
            "requester_role_slug": f"{requester}-lead",
        },
    )
    tid_p3 = r_p3.get_json()["задача"]["id"]
    # Потом P1
    r_p1 = client.post(
        f"/api/departments/{target}/tasks",
        json={
            "title": "high pri",
            "priority": "P1",
            "requester_department_id": requester,
            "requester_role_slug": f"{requester}-lead",
        },
    )
    tid_p1 = r_p1.get_json()["задача"]["id"]
    r = client.get(f"/api/departments/{target}?task_id={tid_p1}")
    body = r.get_json()["department"]
    assert body["queue_position"] == 1
    r = client.get(f"/api/departments/{target}?task_id={tid_p3}")
    body = r.get_json()["department"]
    # P3 после P1
    assert body["queue_position"] == 2


def test_department_no_task_id_no_queue_position(client) -> None:
    """GET /api/departments/<id> без task_id → queue_position отсутствует (backward compat)."""
    target = _create_dept(client, "Design")
    r = client.get(f"/api/departments/{target}")
    body = r.get_json()["department"]
    assert "queue_position" not in body
    assert "queue_total" not in body


def test_queue_position_preview(client) -> None:
    """GET /api/departments/<id>/queue-position?priority=P3 → {position, total}."""
    target = _create_dept(client, "Design")
    r = client.get(f"/api/departments/{target}/queue-position?priority=P3")
    assert r.status_code == 200
    body = r.get_json()
    assert "position" in body
    assert "total" in body
    # Пустой отдел: новая P3 будет 1-й (total=1)
    assert body["position"] == 1
    assert body["total"] == 1


# ---------------------------------------------------------------------------
# POST /api/tasks/<id>/approve для cross-task (баг #5933b0f3b933 → ADR-005)
# ---------------------------------------------------------------------------

def _seed_lead_role(db_path, dept_id: str) -> str:
    """Создаёт `<dept>-lead` роль в указанном отделе. Возвращает slug."""
    import sqlite3
    slug = f"{dept_id}-lead"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO roles (name, description, capabilities, department_id) "
            "VALUES (?, ?, ?, ?)",
            (slug, "lead role", "{}", dept_id),
        )
        conn.commit()
    finally:
        conn.close()
    return slug


def test_approve_cross_task_assigns_to_target_lead(client) -> None:
    """Owner approves P1 cross-task → assignee становится Lead отдела-исполнителя.

    Семантика ADR-005: reporter (заказчик, marketing-lead) — это НЕ исполнитель.
    После approve задача должна попасть к Lead отдела-исполнителя (design-lead),
    а не вернуться на reporter'а (как было в legacy intra-task логике).
    Раньше падало 400 (баг #5933b0f3b933): assignee=marketing-lead не входит
    в whitelist ROLES в tools.update_task.
    """
    from pathlib import Path
    target = _create_dept(client, "Design")
    requester = _create_dept(client, "Marketing")
    db_path = Path(client.application.config["DB_PATH"])
    # Сидим Lead-роль в target отделе — её должен подобрать _find_lead_for_department.
    _seed_lead_role(db_path, target)

    # P1 cross-task → needs_approval
    r = client.post(
        f"/api/departments/{target}/tasks",
        json={
            "title": "Срочный rebrand",
            "priority": "P1",
            "requester_department_id": requester,
            "requester_role_slug": f"{requester}-lead",
        },
    )
    assert r.status_code == 201, r.get_data(as_text=True)
    task = r.get_json()["задача"]
    tid = task["id"]
    assert task["status"] == "needs_approval"
    assert task["assignee"] == "пользователь"

    # Owner approves через штатный endpoint
    r = client.post(f"/api/tasks/{tid}/approve", json={"text": "ок, делаем"})
    assert r.status_code == 200, r.get_data(as_text=True)
    approved = r.get_json()["задача"]
    assert approved["status"] == "todo"
    # Главное: assignee = Lead отдела-исполнителя (target=design), а не reporter.
    assert approved["assignee"] == f"{target}-lead", (
        f"ожидали assignee=={target}-lead, получили {approved['assignee']!r}"
    )


def test_approve_cross_task_fallback_when_no_target_lead(client) -> None:
    """Cross-task approve когда у target нет Lead-роли → fallback на 'пользователь'.

    Не падает 400; owner оставляет задачу себе для дальнейшего разруливания.
    """
    target = _create_dept(client, "Design")
    requester = _create_dept(client, "Marketing")
    # Намеренно НЕ создаём Lead-роль в target.

    r = client.post(
        f"/api/departments/{target}/tasks",
        json={
            "title": "Срочный rebrand без лида",
            "priority": "P1",
            "requester_department_id": requester,
            "requester_role_slug": f"{requester}-lead",
        },
    )
    assert r.status_code == 201
    tid = r.get_json()["задача"]["id"]

    r = client.post(f"/api/tasks/{tid}/approve", json={"text": "ок"})
    assert r.status_code == 200, r.get_data(as_text=True)
    approved = r.get_json()["задача"]
    assert approved["status"] == "todo"
    # Без Lead-роли — owner оставляет себе (валидный slug из ROLES).
    assert approved["assignee"] == "пользователь"


def test_approve_intra_task_backward_compat(client) -> None:
    """Approve обычной (не cross) задачи: assignee = reporter (legacy v1.x).

    Backward-compat: для задач без requester_department_id поведение прежнее —
    assignee возвращается на reporter'а (или 'тимлид' если reporter=None).
    """
    # Обычная задача с reporter='тимлид', status=needs_approval, assignee=пользователь
    r = client.post(
        "/api/tasks",
        json={
            "title": "intra approval task",
            "reporter": "тимлид",
            "assignee": "пользователь",
            "status": "needs_approval",
            "requires_approval": True,
        },
    )
    assert r.status_code == 201, r.get_data(as_text=True)
    tid = r.get_json()["задача"]["id"]

    r = client.post(f"/api/tasks/{tid}/approve", json={"text": "ок"})
    assert r.status_code == 200, r.get_data(as_text=True)
    approved = r.get_json()["задача"]
    assert approved["status"] == "todo"
    # Legacy: возвращаем reporter'у
    assert approved["assignee"] == "тимлид"

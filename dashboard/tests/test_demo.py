"""Тесты для POST/DELETE /api/demo — эндпоинт демо-режима.

Покрытие:
  - test_create_demo_creates_tasks: POST создаёт 5 задач с нужными полями
  - test_create_demo_idempotent: повторный POST не создаёт дубли
  - test_clear_demo_deletes_demo_tasks: DELETE удаляет задачи с label "demo"
  - test_clear_demo_doesnt_delete_non_demo: DELETE не трогает обычные задачи

Запуск: python -m pytest dashboard/tests/test_demo.py -v
"""

from __future__ import annotations


def test_create_demo_creates_tasks(client) -> None:
    """POST /api/demo создаёт 5 демо-задач и возвращает их id."""
    r = client.post("/api/demo")
    assert r.status_code == 201
    j = r.get_json()
    assert j["already_exists"] is False
    assert len(j["created"]) == 5

    # Все 5 id уникальны
    assert len(set(j["created"])) == 5

    # Проверяем что задачи реально есть в канбане
    tasks_r = client.get("/api/tasks")
    assert tasks_r.status_code == 200
    all_tasks = tasks_r.get_json()["задачи"]

    # Все созданные id должны быть в канбане
    task_ids_in_board = {t["id"] for t in all_tasks}
    for tid in j["created"]:
        assert tid in task_ids_in_board, f"задача {tid} не найдена в канбане"

    # Проверяем наличие epic «Build a landing page» (status=wip, label=demo)
    demo_tasks = [t for t in all_tasks if "demo" in t.get("labels", [])]
    assert len(demo_tasks) == 5

    titles = {t["title"] for t in demo_tasks}
    assert "Build a landing page" in titles
    assert "Deploy to production" in titles

    # Epic должен быть в статусе wip
    epic = next(t for t in demo_tasks if t["title"] == "Build a landing page")
    assert epic["status"] == "wip"
    assert "demo" in epic["labels"]

    # Deploy to production — needs_approval + destructive label
    deploy = next(t for t in demo_tasks if t["title"] == "Deploy to production")
    assert deploy["status"] == "needs_approval"
    assert "demo" in deploy["labels"]
    assert "destructive" in deploy["labels"]
    assert deploy["requires_approval"] is True

    # Проверяем что 3 подзадачи с разными статусами существуют
    subtask_statuses = {
        t["status"] for t in demo_tasks
        if t["title"] not in ("Build a landing page", "Deploy to production")
    }
    assert "todo" in subtask_statuses
    assert "wip" in subtask_statuses
    assert "review" in subtask_statuses


def test_create_demo_idempotent(client) -> None:
    """Повторный POST /api/demo не создаёт дубли — возвращает already_exists=True."""
    # Первый вызов
    r1 = client.post("/api/demo")
    assert r1.status_code == 201
    j1 = r1.get_json()
    assert j1["already_exists"] is False
    first_ids = set(j1["created"])
    assert len(first_ids) == 5

    # Второй вызов — должен вернуть 200 с already_exists=True
    r2 = client.post("/api/demo")
    assert r2.status_code == 200
    j2 = r2.get_json()
    assert j2["already_exists"] is True
    assert j2["created"] == []

    # В канбане всё ещё ровно 5 демо-задач (не 10)
    tasks_r = client.get("/api/tasks")
    demo_tasks = [
        t for t in tasks_r.get_json()["задачи"]
        if "demo" in t.get("labels", [])
    ]
    assert len(demo_tasks) == 5


def test_clear_demo_deletes_demo_tasks(client) -> None:
    """DELETE /api/demo удаляет все задачи с label "demo"."""
    # Создаём демо-данные
    r_create = client.post("/api/demo")
    assert r_create.status_code == 201
    assert len(r_create.get_json()["created"]) == 5

    # Удаляем
    r_delete = client.delete("/api/demo")
    assert r_delete.status_code == 200
    j = r_delete.get_json()
    assert j["deleted"] == 5

    # Проверяем что в канбане не осталось demo-задач
    tasks_r = client.get("/api/tasks")
    demo_tasks = [
        t for t in tasks_r.get_json()["задачи"]
        if "demo" in t.get("labels", [])
    ]
    assert demo_tasks == []


def test_clear_demo_doesnt_delete_non_demo(client) -> None:
    """DELETE /api/demo НЕ удаляет обычные задачи без label "demo"."""
    # Создаём обычную задачу (без demo label)
    r_normal = client.post(
        "/api/tasks",
        json={
            "title": "Обычная задача без demo",
            "description": "Эта задача должна остаться после clear_demo.",
            "labels": ["production", "important"],
        },
    )
    assert r_normal.status_code == 201
    normal_id = r_normal.get_json()["задача"]["id"]

    # Создаём демо-данные
    r_demo = client.post("/api/demo")
    assert r_demo.status_code == 201

    # Удаляем только демо
    r_delete = client.delete("/api/demo")
    assert r_delete.status_code == 200
    assert r_delete.get_json()["deleted"] == 5

    # Обычная задача должна остаться
    r_check = client.get(f"/api/tasks/{normal_id}")
    assert r_check.status_code == 200
    task = r_check.get_json()["задача"]
    assert task["title"] == "Обычная задача без demo"
    assert "demo" not in task.get("labels", [])

    # Всего в канбане — только 1 задача (обычная)
    tasks_r = client.get("/api/tasks")
    all_tasks = tasks_r.get_json()["задачи"]
    assert len(all_tasks) == 1
    assert all_tasks[0]["id"] == normal_id

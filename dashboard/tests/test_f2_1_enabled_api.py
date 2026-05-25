"""API-тесты F2.1: PATCH /api/tasks/<id> с enabled, GET возвращает enabled."""

from __future__ import annotations


def test_patch_enabled_false(client) -> None:
    """PATCH {enabled: false} возвращает 200 с {id, enabled: false}."""
    tid = client.post("/api/tasks", json={"title": "toggle"}).get_json()["задача"]["id"]
    r = client.patch(f"/api/tasks/{tid}", json={"enabled": False})
    assert r.status_code == 200
    body = r.get_json()
    assert body["id"] == tid
    assert body["enabled"] is False


def test_patch_enabled_true(client) -> None:
    """PATCH {enabled: true} возвращает 200 с {id, enabled: true}."""
    tid = client.post("/api/tasks", json={"title": "toggle2"}).get_json()["задача"]["id"]
    # Сначала отключаем
    client.patch(f"/api/tasks/{tid}", json={"enabled": False})
    # Затем включаем обратно
    r = client.patch(f"/api/tasks/{tid}", json={"enabled": True})
    assert r.status_code == 200
    body = r.get_json()
    assert body["enabled"] is True


def test_patch_enabled_404(client) -> None:
    """PATCH на несуществующую задачу возвращает 404."""
    r = client.patch("/api/tasks/nonexistent00", json={"enabled": False})
    assert r.status_code == 404


def test_get_task_returns_enabled_field(client) -> None:
    """GET /api/tasks/<id> возвращает поле enabled."""
    r = client.post("/api/tasks", json={"title": "enabled check"})
    task = r.get_json()["задача"]
    tid = task["id"]
    # Изначально enabled=True
    assert task["enabled"] is True
    # После PATCH — GET должен отразить изменение
    client.patch(f"/api/tasks/{tid}", json={"enabled": False})
    r2 = client.get(f"/api/tasks/{tid}")
    assert r2.status_code == 200
    assert r2.get_json()["задача"]["enabled"] is False


def test_patch_enabled_does_not_break_other_fields(client) -> None:
    """PATCH enabled не трогает status, title и другие поля."""
    r = client.post("/api/tasks", json={"title": "важная", "assignee": "бэкенд"})
    task = r.get_json()["задача"]
    tid = task["id"]

    client.patch(f"/api/tasks/{tid}", json={"enabled": False})

    fetched = client.get(f"/api/tasks/{tid}").get_json()["задача"]
    assert fetched["title"] == "важная"
    assert fetched["status"] == "todo"
    assert fetched["assignee"] == "бэкенд"
    assert fetched["enabled"] is False


def test_create_task_has_enabled_true_by_default(client) -> None:
    """POST /api/tasks создаёт задачу с enabled=True."""
    r = client.post("/api/tasks", json={"title": "default enabled"})
    assert r.status_code == 201
    task = r.get_json()["задача"]
    assert task["enabled"] is True

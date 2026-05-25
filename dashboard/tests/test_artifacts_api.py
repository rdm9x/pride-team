"""REST-тесты для endpoints артефактов задач."""

from __future__ import annotations

from devboard_tasks import db


def test_get_empty_artifacts(client) -> None:
    """Тест получения артефактов для задачи без них."""
    # Создаём задачу
    r = client.post(
        "/api/tasks",
        json={
            "title": "Задача",
            "description": "Описание",
        },
    )
    task_id = r.get_json()["задача"]["id"]

    # Получаем артефакты (должна быть пустая прямо)
    r = client.get(f"/api/tasks/{task_id}/artifacts")
    assert r.status_code == 200
    data = r.get_json()
    assert data["статус"] == "ok"
    assert data["artifacts"] == []


def test_get_artifacts_with_content(client, tmp_path) -> None:
    """Тест получения артефактов с содержимым."""
    # Создаём задачу
    r = client.post(
        "/api/tasks",
        json={
            "title": "Задача",
            "description": "Описание",
        },
    )
    task_id = r.get_json()["задача"]["id"]

    # Добавляем артефакты в БД напрямую
    db_path = client.application.config.get("DEVBOARD_TASKS_DB")
    artifact1 = db.insert_artifact(
        db_path,
        task_id,
        "/path/to/logfile.txt",
        "log",
    )
    artifact2 = db.insert_artifact(
        db_path,
        task_id,
        "/path/to/screenshot.png",
        "screenshot",
    )

    # Получаем артефакты
    r = client.get(f"/api/tasks/{task_id}/artifacts")
    assert r.status_code == 200
    data = r.get_json()
    assert data["статус"] == "ok"
    assert len(data["artifacts"]) == 2

    # Проверяем структуру первого артефакта
    art = data["artifacts"][0]
    assert "id" in art
    assert "task_id" in art
    assert "file_path" in art
    assert "kind" in art
    assert "created_at" in art


def test_get_artifacts_ordered_by_created_at(client) -> None:
    """Тест что артефакты возвращаются в обратном хронологическом порядке."""
    # Создаём задачу
    r = client.post(
        "/api/tasks",
        json={
            "title": "Задача",
            "description": "Описание",
        },
    )
    task_id = r.get_json()["задача"]["id"]

    # Добавляем артефакты с разными timestamps
    db_path = client.application.config.get("DEVBOARD_TASKS_DB")
    import time

    time_1 = int(time.time())
    artifact1 = db.insert_artifact(
        db_path,
        task_id,
        "/path/to/file1.txt",
        "log",
        created_at=time_1,
    )

    time.sleep(0.1)
    time_2 = int(time.time())
    artifact2 = db.insert_artifact(
        db_path,
        task_id,
        "/path/to/file2.txt",
        "result",
        created_at=time_2,
    )

    # Получаем артефакты
    r = client.get(f"/api/tasks/{task_id}/artifacts")
    assert r.status_code == 200
    data = r.get_json()
    artifacts = data["artifacts"]

    # Проверяем что они отсортированы по created_at DESC
    assert len(artifacts) == 2
    assert artifacts[0]["created_at"] >= artifacts[1]["created_at"]
    assert artifacts[0]["file_path"] == "/path/to/file2.txt"
    assert artifacts[1]["file_path"] == "/path/to/file1.txt"


def test_artifact_kinds_supported(client) -> None:
    """Тест что поддерживаются разные типы артефактов."""
    # Создаём задачу
    r = client.post(
        "/api/tasks",
        json={
            "title": "Задача",
            "description": "Описание",
        },
    )
    task_id = r.get_json()["задача"]["id"]

    # Добавляем артефакты разных типов
    db_path = client.application.config.get("DEVBOARD_TASKS_DB")
    kinds = ["log", "result", "screenshot", "report", "code", "file"]
    for i, kind in enumerate(kinds):
        db.insert_artifact(
            db_path,
            task_id,
            f"/path/to/file_{i}.bin",
            kind,
        )

    # Получаем артефакты
    r = client.get(f"/api/tasks/{task_id}/artifacts")
    assert r.status_code == 200
    data = r.get_json()
    artifacts = data["artifacts"]

    # Проверяем что все типы сохранились
    assert len(artifacts) == len(kinds)
    received_kinds = {a["kind"] for a in artifacts}
    assert received_kinds == set(kinds)

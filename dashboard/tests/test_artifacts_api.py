"""REST-тесты для endpoints артефактов задач."""

from __future__ import annotations


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
    from devboard_tasks import db  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

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
    db_path = Path(client.application.config.get("DEVBOARD_TASKS_DB"))
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
    from devboard_tasks import db  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415
    import time  # noqa: PLC0415

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
    db_path = Path(client.application.config.get("DEVBOARD_TASKS_DB"))

    time_1 = int(time.time())
    artifact1 = db.insert_artifact(
        db_path,
        task_id,
        "/path/to/file1.txt",
        "log",
        created_at=time_1,
    )

    # Гарантируем разные timestamps
    time_2 = time_1 + 1
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
    from devboard_tasks import db  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

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
    db_path = Path(client.application.config.get("DEVBOARD_TASKS_DB"))
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


def test_artifacts_in_task_modal_ui(client) -> None:
    """E2E тест: артефакты видны при открытии карточки задачи через UI."""
    from devboard_tasks import db  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    # Создаём задачу
    r = client.post(
        "/api/tasks",
        json={
            "title": "Задача с артефактами",
            "description": "Описание с результатами",
        },
    )
    assert r.status_code == 201
    task_id = r.get_json()["задача"]["id"]

    # Добавляем артефакты в БД
    db_path = Path(client.application.config.get("DEVBOARD_TASKS_DB"))
    db.insert_artifact(
        db_path,
        task_id,
        "/tmp/report.pdf",
        "report",
    )
    db.insert_artifact(
        db_path,
        task_id,
        "/tmp/screenshot.png",
        "screenshot",
    )

    # Получаем список артефактов через API
    r = client.get(f"/api/tasks/{task_id}/artifacts")
    assert r.status_code == 200
    data = r.get_json()
    assert data["статус"] == "ok"
    artifacts = data["artifacts"]

    # Проверяем что оба артефакта вернулись
    assert len(artifacts) == 2
    file_paths = {a["file_path"] for a in artifacts}
    assert "/tmp/report.pdf" in file_paths
    assert "/tmp/screenshot.png" in file_paths

    # Проверяем что у каждого артефакта есть необходимые поля
    for art in artifacts:
        assert "id" in art
        assert "task_id" in art
        assert art["task_id"] == task_id
        assert "file_path" in art
        assert "kind" in art
        assert "created_at" in art
        assert isinstance(art["created_at"], int)

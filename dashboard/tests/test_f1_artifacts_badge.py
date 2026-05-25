"""E2E tests для F1: UI карточки с бейджем артефактов."""

from __future__ import annotations


def test_task_card_shows_artifact_badge_when_has_artifacts(client) -> None:
    """Тест: карточка задачи показывает бейдж с количеством артефактов."""
    from devboard_tasks import db
    from pathlib import Path

    # Создаём задачу
    r = client.post(
        "/api/tasks",
        json={
            "title": "Задача с артефактами",
            "description": "Описание задачи",
        },
    )
    assert r.status_code == 201
    task_id = r.get_json()["задача"]["id"]

    # Добавляем 2 артефакта
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

    # Запрашиваем список задач (которые показывают на доске)
    r = client.get("/api/tasks?department=dev")
    assert r.status_code == 200
    data = r.get_json()

    # Ищем нашу задачу в ответе
    found = False
    for t in data.get("задачи", []):
        if t["id"] == task_id:
            found = True
            # Проверяем что artifact_count = 2
            assert t.get("artifact_count") == 2, f"Expected artifact_count=2, got {t.get('artifact_count')}"
            break

    assert found, f"Task {task_id} not found in list"


def test_task_card_artifact_count_zero_when_no_artifacts(client) -> None:
    """Тест: карточка задачи без артефактов показывает artifact_count=0."""
    # Создаём задачу
    r = client.post(
        "/api/tasks",
        json={
            "title": "Задача без артефактов",
            "description": "Описание",
        },
    )
    assert r.status_code == 201
    task_id = r.get_json()["задача"]["id"]

    # Запрашиваем список задач
    r = client.get("/api/tasks?department=dev")
    assert r.status_code == 200
    data = r.get_json()

    # Ищем нашу задачу
    found = False
    for t in data.get("задачи", []):
        if t["id"] == task_id:
            found = True
            # artifact_count должен быть 0 или отсутствовать
            assert t.get("artifact_count", 0) == 0
            break

    assert found, f"Task {task_id} not found in list"


def test_artifacts_endpoint_returns_list(client) -> None:
    """Тест: GET /api/tasks/<id>/artifacts возвращает корректный список."""
    from devboard_tasks import db
    from pathlib import Path

    # Создаём задачу
    r = client.post(
        "/api/tasks",
        json={
            "title": "Задача",
            "description": "Описание",
        },
    )
    task_id = r.get_json()["задача"]["id"]

    # Добавляем артефакты
    db_path = Path(client.application.config.get("DEVBOARD_TASKS_DB"))
    db.insert_artifact(
        db_path,
        task_id,
        "/tmp/result.json",
        "result",
    )

    # Получаем артефакты через API
    r = client.get(f"/api/tasks/{task_id}/artifacts")
    assert r.status_code == 200
    data = r.get_json()
    assert data["статус"] == "ok"
    assert len(data["artifacts"]) == 1
    assert data["artifacts"][0]["kind"] == "result"
    assert data["artifacts"][0]["file_path"] == "/tmp/result.json"


def test_artifacts_ui_renders_correctly(client) -> None:
    """Тест: UI блок артефактов отображается корректно с кнопками открытия."""
    from devboard_tasks import db
    from pathlib import Path

    # Создаём задачу в статусе review (где видны артефакты)
    r = client.post(
        "/api/tasks",
        json={
            "title": "Task with artifacts for UI test",
            "description": "Description",
            "status": "review",
        },
    )
    assert r.status_code == 201
    task_id = r.get_json()["задача"]["id"]

    # Добавляем артефакты разных типов
    db_path = Path(client.application.config.get("DEVBOARD_TASKS_DB"))
    db.insert_artifact(db_path, task_id, "workspace/project/report.pdf", "report")
    db.insert_artifact(db_path, task_id, "workspace/project/screenshot.png", "screenshot")
    db.insert_artifact(db_path, task_id, "workspace/project/code.js", "code")

    # Получаем список задач и проверяем artifact_count
    r = client.get("/api/tasks?department=dev")
    assert r.status_code == 200
    data = r.get_json()

    task = None
    for t in data["задачи"]:
        if t["id"] == task_id:
            task = t
            break

    assert task is not None, f"Task {task_id} not found in list"
    assert task["artifact_count"] == 3, f"Expected 3 artifacts, got {task['artifact_count']}"

    # Получаем артефакты через API (это то, что фронт загружает при открытии модального окна)
    r = client.get(f"/api/tasks/{task_id}/artifacts")
    assert r.status_code == 200
    artifacts_data = r.get_json()
    assert artifacts_data["статус"] == "ok"
    artifacts = artifacts_data["artifacts"]

    assert len(artifacts) == 3, f"Expected 3 artifacts, got {len(artifacts)}"

    # Проверяем что каждый артефакт имеет необходимые поля для UI
    for art in artifacts:
        assert "id" in art
        assert "task_id" in art
        assert "file_path" in art
        assert "kind" in art
        assert "created_at" in art
        # file_path должен быть полным путём для window.open('file:///'...)
        assert art["file_path"].startswith("workspace/")

    # Проверяем что есть разные типы (для правильного выбора иконок)
    kinds = {a["kind"] for a in artifacts}
    assert "report" in kinds
    assert "screenshot" in kinds
    assert "code" in kinds

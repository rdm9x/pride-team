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


def test_open_file_missing_path(client) -> None:
    """Тест что POST /api/open-file требует path."""
    r = client.post("/api/open-file", json={})
    assert r.status_code == 400
    data = r.get_json()
    assert data["status"] == "error"
    assert "path" in data["reason"].lower()


def test_open_file_empty_path(client) -> None:
    """Тест что пустой path отклоняется."""
    r = client.post("/api/open-file", json={"path": "   "})
    assert r.status_code == 400
    data = r.get_json()
    assert data["status"] == "error"


def test_open_file_path_traversal_attack(client) -> None:
    """Тест что path traversal атаки блокируются."""
    # Пытаемся обойти workspace/ ограничение
    r = client.post("/api/open-file", json={"path": "../../../etc/passwd"})
    assert r.status_code == 403
    data = r.get_json()
    assert data["status"] == "error"
    assert "workspace" in data["reason"].lower()


def test_open_file_outside_workspace(client) -> None:
    """Тест что доступ вне workspace/ блокируется."""
    r = client.post("/api/open-file", json={"path": "data/tasks.db"})
    assert r.status_code == 403
    data = r.get_json()
    assert data["status"] == "error"
    assert "workspace" in data["reason"].lower()


def test_open_file_not_found(client) -> None:
    """Тест что несуществующий файл возвращает 404."""
    r = client.post("/api/open-file", json={"path": "workspace/nonexistent/file.txt"})
    assert r.status_code == 404
    data = r.get_json()
    assert data["status"] == "error"
    assert "not found" in data["reason"].lower()


def test_open_file_directory_rejected(client, tmp_path) -> None:
    """Тест что endpoint отклоняет папки (используй /api/open-folder)."""
    from pathlib import Path  # noqa: PLC0415
    import os  # noqa: PLC0415

    # Создаём временный workspace с папкой
    workspace_root = Path(client.application.config.get("REPO_ROOT")) / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)

    test_dir = workspace_root / "test_project"
    test_dir.mkdir(exist_ok=True)

    try:
        r = client.post("/api/open-file", json={"path": "workspace/test_project"})
        assert r.status_code == 400
        data = r.get_json()
        assert data["status"] == "error"
        assert "files only" in data["reason"].lower()
    finally:
        # Очищаем
        if test_dir.exists():
            os.rmdir(test_dir)


def test_open_file_success(client, tmp_path) -> None:
    """Тест успешного открытия файла."""
    from pathlib import Path  # noqa: PLC0415

    # Создаём временный файл в workspace
    workspace_root = Path(client.application.config.get("REPO_ROOT")) / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)

    test_file = workspace_root / "test_file.txt"
    test_file.write_text("test content")

    try:
        r = client.post("/api/open-file", json={"path": "workspace/test_file.txt"})
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] == "opened"
        assert data["file_path"] == "workspace/test_file.txt"
        assert "absolute_path" in data
        assert "workspace/test_file.txt" in data["absolute_path"]
    finally:
        # Очищаем
        if test_file.exists():
            test_file.unlink()


def test_open_folder_workspace_allowed(client) -> None:
    """Тест что POST /api/open-folder разрешает workspace/ пути."""
    from pathlib import Path  # noqa: PLC0415
    import os  # noqa: PLC0415

    workspace_root = Path(client.application.config.get("REPO_ROOT")) / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)

    test_dir = workspace_root / "test_project"
    test_dir.mkdir(exist_ok=True)

    try:
        r = client.post("/api/open-folder", json={"path": "workspace/test_project"})
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] == "ok"
        assert "path" in data
    finally:
        # Очищаем
        if test_dir.exists():
            os.rmdir(test_dir)


def test_open_folder_data_still_allowed(client) -> None:
    """Тест что /api/open-folder всё ещё разрешает data/ пути (backwards compat)."""
    r = client.post("/api/open-folder", json={"path": "data"})
    assert r.status_code == 200
    data = r.get_json()
    assert data["status"] == "ok"


def test_open_folder_path_traversal_blocked(client) -> None:
    """Тест что path traversal атаки в /api/open-folder блокируются."""
    r = client.post("/api/open-folder", json={"path": "../../../etc"})
    assert r.status_code == 403
    data = r.get_json()
    assert data["status"] == "error"
    assert "workspace" in data["reason"].lower() or "data" in data["reason"].lower()


def test_open_folder_missing_path(client) -> None:
    """Тест что /api/open-folder требует path."""
    r = client.post("/api/open-folder", json={})
    assert r.status_code == 400
    data = r.get_json()
    assert data["status"] == "error"
    assert "path" in data["reason"].lower()

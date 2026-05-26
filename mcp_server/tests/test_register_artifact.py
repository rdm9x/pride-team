"""Тесты для MCP tool register_task_artifact (после введения проектов)."""

from __future__ import annotations

from pathlib import Path

import pytest

from devboard_tasks import db, tools


def _make_task_with_project(
    db_path: Path,
    *,
    project_slug: str = "test-proj",
    project_title: str = "Test Project",
    task_title: str = "Test task",
    department_id: str = "dev",
) -> tuple[dict, dict]:
    """Создаёт проект и задачу в нём. Возвращает (project, task)."""
    project = db.create_project(db_path, slug=project_slug, title=project_title)
    task = db.insert_task(db_path, title=task_title, department_id=department_id)
    db.link_task_to_project(db_path, task["id"], project["id"])
    # Обновляем task чтобы у него был project_id
    task = db.get_task(db_path, task["id"])
    return project, task


def _expected_prefix(project: dict, task: dict) -> str:
    dept = task.get("department_id") or "general"
    return f"workspace/{project['code']}-{project['slug']}/{dept}/{task['id']}/"


# ============================================================================
# Unit-тесты: register_task_artifact
# ============================================================================


def test_register_artifact_basic(db_path: Path) -> None:
    """Unit: зарегистрировать артефакт с базовыми параметрами."""
    project, task = _make_task_with_project(db_path)
    expected = _expected_prefix(project, task) + "result.pdf"

    result = tools.register_task_artifact(
        task_id=task["id"],
        file_path="result.pdf",   # basename — функция сама пристроит префикс
        kind="report",
        db_path=db_path,
    )

    assert result["статус"] == "ok"
    assert result["status"] == "ok"
    assert result["artifact_id"] is not None
    assert result["task_id"] == task["id"]
    assert result["file_path"] == expected
    assert result["kind"] == "report"
    assert isinstance(result["created_at"], int)


def test_register_artifact_default_kind(db_path: Path) -> None:
    """Unit: kind по умолчанию 'artifact'."""
    _project, task = _make_task_with_project(db_path)

    result = tools.register_task_artifact(
        task_id=task["id"],
        file_path="file.txt",
        db_path=db_path,
    )

    assert result["статус"] == "ok"
    assert result["kind"] == "artifact"


def test_register_artifact_missing_task_id(db_path: Path) -> None:
    """Unit: ошибка если task_id пустой."""
    result = tools.register_task_artifact(
        task_id="",
        file_path="file.txt",
        db_path=db_path,
    )

    assert result["статус"] == "error"
    assert "task_id пустой" in result["причина"]


def test_register_artifact_missing_file_path(db_path: Path) -> None:
    """Unit: ошибка если file_path пустой."""
    _project, task = _make_task_with_project(db_path)

    result = tools.register_task_artifact(
        task_id=task["id"],
        file_path="",
        db_path=db_path,
    )

    assert result["статус"] == "error"
    assert "file_path пустой" in result["причина"]


def test_register_artifact_task_not_found(db_path: Path) -> None:
    """Unit: ошибка если task не существует."""
    result = tools.register_task_artifact(
        task_id="nonexistent_task_id",
        file_path="file.txt",
        db_path=db_path,
    )

    assert result["статус"] == "not_found"
    assert "не найдена" in result["причина"]


def test_register_artifact_task_without_project_error(db_path: Path) -> None:
    """Unit: задача без project_id не принимает артефакты — куда сохранять?"""
    task = db.insert_task(db_path, title="Orphan task")

    result = tools.register_task_artifact(
        task_id=task["id"],
        file_path="file.txt",
        db_path=db_path,
    )

    assert result["статус"] == "error"
    assert "не привязана к проекту" in result["причина"]


def test_register_artifact_absolute_path_error(db_path: Path) -> None:
    """Unit: ошибка если file_path абсолютный."""
    _project, task = _make_task_with_project(db_path)

    result = tools.register_task_artifact(
        task_id=task["id"],
        file_path="/absolute/path/file.txt",
        db_path=db_path,
    )

    assert result["статус"] == "error"
    assert "относительным" in result["причина"]


def test_register_artifact_path_traversal_error(db_path: Path) -> None:
    """Unit: ошибка если file_path содержит .."""
    _project, task = _make_task_with_project(db_path)

    result = tools.register_task_artifact(
        task_id=task["id"],
        file_path="workspace/../../../etc/passwd",
        db_path=db_path,
    )

    assert result["статус"] == "error"
    assert ".." in result["причина"]


def test_register_artifact_path_outside_project_dir_error(db_path: Path) -> None:
    """Unit: file_path внутри workspace/ но НЕ в папке проекта — отказ."""
    _project, task = _make_task_with_project(db_path)

    result = tools.register_task_artifact(
        task_id=task["id"],
        file_path="workspace/random-folder/file.txt",
        db_path=db_path,
    )

    assert result["статус"] == "error"
    assert "должен быть внутри" in result["причина"]


def test_register_artifact_full_valid_path_accepted(db_path: Path) -> None:
    """Unit: если автор сразу дал полный путь по схеме — принимается без изменений."""
    project, task = _make_task_with_project(db_path)
    full = _expected_prefix(project, task) + "report.pdf"

    result = tools.register_task_artifact(
        task_id=task["id"],
        file_path=full,
        db_path=db_path,
    )

    assert result["статус"] == "ok"
    assert result["file_path"] == full


def test_register_artifact_multiple_kinds(db_path: Path) -> None:
    """Unit: различные типы артефактов."""
    _project, task = _make_task_with_project(db_path)

    for kind in ["artifact", "log", "report", "screenshot", "custom_type"]:
        result = tools.register_task_artifact(
            task_id=task["id"],
            file_path=f"{kind}.txt",
            kind=kind,
            db_path=db_path,
        )

        assert result["статус"] == "ok"
        assert result["kind"] == kind


# ============================================================================
# Integration-тесты с БД
# ============================================================================


def test_register_artifact_integration_db_record(db_path: Path) -> None:
    """Integration: verify record in DB after register_task_artifact."""
    project, task = _make_task_with_project(db_path)

    result = tools.register_task_artifact(
        task_id=task["id"],
        file_path="result.pdf",
        kind="report",
        db_path=db_path,
    )
    assert result["статус"] == "ok"
    artifact_id = result["artifact_id"]

    artifact_from_db = db.get_artifact(db_path, artifact_id)
    assert artifact_from_db is not None
    assert artifact_from_db["id"] == artifact_id
    assert artifact_from_db["task_id"] == task["id"]
    assert artifact_from_db["file_path"] == _expected_prefix(project, task) + "result.pdf"
    assert artifact_from_db["kind"] == "report"
    assert artifact_from_db["created_at"] == result["created_at"]


def test_register_artifact_integration_list_artifacts(db_path: Path) -> None:
    """Integration: артефакты видны в list_artifacts после регистрации."""
    _project, task = _make_task_with_project(db_path)

    a1_result = tools.register_task_artifact(
        task_id=task["id"], file_path="a1.log", kind="log", db_path=db_path,
    )
    a2_result = tools.register_task_artifact(
        task_id=task["id"], file_path="a2.pdf", kind="report", db_path=db_path,
    )

    artifacts = db.list_artifacts(db_path, task["id"])
    assert len(artifacts) == 2

    artifact_ids = {a["id"] for a in artifacts}
    assert a1_result["artifact_id"] in artifact_ids
    assert a2_result["artifact_id"] in artifact_ids


def test_register_artifact_integration_different_tasks(db_path: Path) -> None:
    """Integration: артефакты разных задач изолированы."""
    project1, task1 = _make_task_with_project(
        db_path, project_slug="proj-a", project_title="A", task_title="Task 1"
    )
    project2, task2 = _make_task_with_project(
        db_path, project_slug="proj-b", project_title="B", task_title="Task 2"
    )

    result1 = tools.register_task_artifact(
        task_id=task1["id"], file_path="file1.txt", db_path=db_path,
    )
    result2 = tools.register_task_artifact(
        task_id=task2["id"], file_path="file2.txt", db_path=db_path,
    )

    artifacts1 = db.list_artifacts(db_path, task1["id"])
    artifacts2 = db.list_artifacts(db_path, task2["id"])

    assert len(artifacts1) == 1
    assert len(artifacts2) == 1
    assert artifacts1[0]["id"] == result1["artifact_id"]
    assert artifacts2[0]["id"] == result2["artifact_id"]


def test_register_artifact_integration_unique_constraint(db_path: Path) -> None:
    """Integration: уникальность constraint (task_id, file_path) работает."""
    _project, task = _make_task_with_project(db_path)

    result1 = tools.register_task_artifact(
        task_id=task["id"], file_path="same_file.txt", db_path=db_path,
    )
    assert result1["статус"] == "ok"

    # Вторая регистрация того же файла — конфликт.
    result2 = tools.register_task_artifact(
        task_id=task["id"], file_path="same_file.txt", db_path=db_path,
    )
    assert result2["статус"] == "error"
    assert "ошибка" in result2["причина"].lower()

"""Тесты для MCP tool register_task_artifact."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from devboard_tasks import db, tools


# ============================================================================
# Unit-тесты: register_task_artifact
# ============================================================================


def test_register_artifact_basic(db_path: Path) -> None:
    """Unit: зарегистрировать артефакт с базовыми параметрами."""
    task = db.insert_task(db_path, title="Test task")

    result = tools.register_task_artifact(
        task_id=task["id"],
        file_path="workspace/result.pdf",
        kind="report",
        db_path=db_path,
    )

    assert result["статус"] == "ok"
    assert result["status"] == "ok"
    assert result["artifact_id"] is not None
    assert result["task_id"] == task["id"]
    assert result["file_path"] == "workspace/result.pdf"
    assert result["kind"] == "report"
    assert result["created_at"] is not None
    assert isinstance(result["created_at"], int)


def test_register_artifact_default_kind(db_path: Path) -> None:
    """Unit: kind по умолчанию 'artifact'."""
    task = db.insert_task(db_path, title="Test task")

    result = tools.register_task_artifact(
        task_id=task["id"],
        file_path="workspace/file.txt",
        db_path=db_path,
    )

    assert result["статус"] == "ok"
    assert result["kind"] == "artifact"


def test_register_artifact_missing_task_id(db_path: Path) -> None:
    """Unit: ошибка если task_id пустой."""
    result = tools.register_task_artifact(
        task_id="",
        file_path="workspace/file.txt",
        db_path=db_path,
    )

    assert result["статус"] == "error"
    assert result["status"] == "error"
    assert "task_id пустой" in result["причина"]


def test_register_artifact_missing_file_path(db_path: Path) -> None:
    """Unit: ошибка если file_path пустой."""
    task = db.insert_task(db_path, title="Test task")

    result = tools.register_task_artifact(
        task_id=task["id"],
        file_path="",
        db_path=db_path,
    )

    assert result["статус"] == "error"
    assert result["status"] == "error"
    assert "file_path пустой" in result["причина"]


def test_register_artifact_task_not_found(db_path: Path) -> None:
    """Unit: ошибка if task не существует."""
    result = tools.register_task_artifact(
        task_id="nonexistent_task_id",
        file_path="workspace/file.txt",
        db_path=db_path,
    )

    assert result["статус"] == "not_found"
    assert result["status"] == "not_found"
    assert "не найдена" in result["причина"]


def test_register_artifact_absolute_path_error(db_path: Path) -> None:
    """Unit: ошибка если file_path абсолютный."""
    task = db.insert_task(db_path, title="Test task")

    result = tools.register_task_artifact(
        task_id=task["id"],
        file_path="/absolute/path/file.txt",
        db_path=db_path,
    )

    assert result["статус"] == "error"
    assert result["status"] == "error"
    assert "относительным" in result["причина"]


def test_register_artifact_path_traversal_error(db_path: Path) -> None:
    """Unit: ошибка если file_path содержит .."""
    task = db.insert_task(db_path, title="Test task")

    result = tools.register_task_artifact(
        task_id=task["id"],
        file_path="workspace/../../../etc/passwd",
        db_path=db_path,
    )

    assert result["статус"] == "error"
    assert result["status"] == "error"
    assert ".." in result["причина"]


def test_register_artifact_valid_relative_paths(db_path: Path) -> None:
    """Unit: валидные относительные пути."""
    task = db.insert_task(db_path, title="Test task")

    # Тест различных валидных путей
    valid_paths = [
        "workspace/file.txt",
        "workspace/subdir/file.pdf",
        "workspace/a/b/c/file.log",
        "file.txt",  # без workspace/ префикса, но валидный
        "logs/output.log",
    ]

    for file_path in valid_paths:
        result = tools.register_task_artifact(
            task_id=task["id"],
            file_path=file_path,
            db_path=db_path,
        )

        assert result["статус"] == "ok", f"Failed for path: {file_path}"
        assert result["file_path"] == file_path


def test_register_artifact_multiple_kinds(db_path: Path) -> None:
    """Unit: различные типы артефактов."""
    task = db.insert_task(db_path, title="Test task")

    kinds = ["artifact", "log", "report", "screenshot", "custom_type"]

    for kind in kinds:
        result = tools.register_task_artifact(
            task_id=task["id"],
            file_path=f"workspace/{kind}.txt",
            kind=kind,
            db_path=db_path,
        )

        assert result["статус"] == "ok"
        assert result["kind"] == kind


# ============================================================================
# Integration-тест с БД: register_task_artifact создаёт корректный record
# ============================================================================


def test_register_artifact_integration_db_record(db_path: Path) -> None:
    """Integration: verify record in DB after register_task_artifact."""
    task = db.insert_task(db_path, title="Integration test task")

    # Регистрируем артефакт через tool
    result = tools.register_task_artifact(
        task_id=task["id"],
        file_path="workspace/result.pdf",
        kind="report",
        db_path=db_path,
    )

    assert result["статус"] == "ok"
    artifact_id = result["artifact_id"]

    # Проверяем что запись создалась в БД
    artifact_from_db = db.get_artifact(db_path, artifact_id)
    assert artifact_from_db is not None
    assert artifact_from_db["id"] == artifact_id
    assert artifact_from_db["task_id"] == task["id"]
    assert artifact_from_db["file_path"] == "workspace/result.pdf"
    assert artifact_from_db["kind"] == "report"
    assert artifact_from_db["created_at"] == result["created_at"]


def test_register_artifact_integration_list_artifacts(db_path: Path) -> None:
    """Integration: артефакты видны в list_artifacts после регистрации."""
    task = db.insert_task(db_path, title="List test task")

    # Регистрируем несколько артефактов
    a1_result = tools.register_task_artifact(
        task_id=task["id"],
        file_path="workspace/a1.log",
        kind="log",
        db_path=db_path,
    )

    a2_result = tools.register_task_artifact(
        task_id=task["id"],
        file_path="workspace/a2.pdf",
        kind="report",
        db_path=db_path,
    )

    # Проверяем list_artifacts
    artifacts = db.list_artifacts(db_path, task["id"])
    assert len(artifacts) == 2

    artifact_ids = {a["id"] for a in artifacts}
    assert a1_result["artifact_id"] in artifact_ids
    assert a2_result["artifact_id"] in artifact_ids


def test_register_artifact_integration_different_tasks(db_path: Path) -> None:
    """Integration: артефакты разных задач изолированы."""
    task1 = db.insert_task(db_path, title="Task 1")
    task2 = db.insert_task(db_path, title="Task 2")

    # Регистрируем артефакты для разных задач
    result1 = tools.register_task_artifact(
        task_id=task1["id"],
        file_path="workspace/file1.txt",
        db_path=db_path,
    )

    result2 = tools.register_task_artifact(
        task_id=task2["id"],
        file_path="workspace/file2.txt",
        db_path=db_path,
    )

    # Проверяем что артефакты связаны с правильными задачами
    artifacts1 = db.list_artifacts(db_path, task1["id"])
    artifacts2 = db.list_artifacts(db_path, task2["id"])

    assert len(artifacts1) == 1
    assert len(artifacts2) == 1
    assert artifacts1[0]["id"] == result1["artifact_id"]
    assert artifacts2[0]["id"] == result2["artifact_id"]


def test_register_artifact_integration_unique_constraint(db_path: Path) -> None:
    """Integration: уникальность constraint (task_id, file_path) работает."""
    task = db.insert_task(db_path, title="Unique test")

    # Первая регистрация должна пройти
    result1 = tools.register_task_artifact(
        task_id=task["id"],
        file_path="workspace/same_file.txt",
        db_path=db_path,
    )
    assert result1["статус"] == "ok"

    # Вторая регистрация с одинаковым file_path должна упасть (constraint нарушен)
    result2 = tools.register_task_artifact(
        task_id=task["id"],
        file_path="workspace/same_file.txt",
        db_path=db_path,
    )

    # Должна быть ошибка (constraint violation)
    assert result2["статус"] == "error"
    assert "ошибка" in result2["причина"].lower()

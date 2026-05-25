"""Тесты для task_artifacts — CRUD операции и отношение с tasks."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from devboard_tasks import db


def test_insert_artifact_minimal(db_path: Path) -> None:
    """CREATE: добавить артефакт с минимальными полями."""
    task = db.insert_task(db_path, title="Task with artifact")
    artifact = db.insert_artifact(
        db_path,
        task_id=task["id"],
        file_path="/tmp/result.log",
        kind="log",
    )

    assert artifact["id"] is not None
    assert artifact["task_id"] == task["id"]
    assert artifact["file_path"] == "/tmp/result.log"
    assert artifact["kind"] == "log"
    assert artifact["created_at"] is not None
    assert isinstance(artifact["created_at"], int)


def test_insert_artifact_with_timestamp(db_path: Path) -> None:
    """CREATE: добавить артефакт с явным timestamp."""
    task = db.insert_task(db_path, title="Task")
    created_at = int(time.time()) - 1000

    artifact = db.insert_artifact(
        db_path,
        task_id=task["id"],
        file_path="/tmp/report.pdf",
        kind="report",
        created_at=created_at,
    )

    assert artifact["created_at"] == created_at


def test_get_artifact(db_path: Path) -> None:
    """READ: получить артефакт по id."""
    task = db.insert_task(db_path, title="Task")
    inserted = db.insert_artifact(
        db_path,
        task_id=task["id"],
        file_path="/tmp/screenshot.png",
        kind="screenshot",
    )

    fetched = db.get_artifact(db_path, inserted["id"])
    assert fetched is not None
    assert fetched["id"] == inserted["id"]
    assert fetched["file_path"] == "/tmp/screenshot.png"
    assert fetched["kind"] == "screenshot"


def test_get_artifact_not_found(db_path: Path) -> None:
    """READ: вернуть None для несуществующего артефакта."""
    fetched = db.get_artifact(db_path, 99999)
    assert fetched is None


def test_list_artifacts_empty(db_path: Path) -> None:
    """READ: вернуть пустой список если артефактов нет."""
    task = db.insert_task(db_path, title="Task")
    artifacts = db.list_artifacts(db_path, task["id"])
    assert artifacts == []


def test_list_artifacts_multiple(db_path: Path) -> None:
    """READ: вернуть все артефакты задачи в порядке created_at DESC."""
    task = db.insert_task(db_path, title="Task")

    a1 = db.insert_artifact(
        db_path, task["id"], "/tmp/a1.log", "log", created_at=100
    )
    a2 = db.insert_artifact(
        db_path, task["id"], "/tmp/a2.log", "log", created_at=200
    )
    a3 = db.insert_artifact(
        db_path, task["id"], "/tmp/a3.log", "log", created_at=150
    )

    artifacts = db.list_artifacts(db_path, task["id"])
    assert len(artifacts) == 3
    assert artifacts[0]["id"] == a2["id"]  # created_at=200 (самый свежий)
    assert artifacts[1]["id"] == a3["id"]  # created_at=150
    assert artifacts[2]["id"] == a1["id"]  # created_at=100


def test_list_artifacts_isolation(db_path: Path) -> None:
    """READ: артефакты одной задачи не влияют на другую."""
    task1 = db.insert_task(db_path, title="Task1")
    task2 = db.insert_task(db_path, title="Task2")

    db.insert_artifact(db_path, task1["id"], "/tmp/a1.log", "log")
    db.insert_artifact(db_path, task1["id"], "/tmp/a2.log", "log")
    db.insert_artifact(db_path, task2["id"], "/tmp/b1.log", "log")

    artifacts1 = db.list_artifacts(db_path, task1["id"])
    artifacts2 = db.list_artifacts(db_path, task2["id"])

    assert len(artifacts1) == 2
    assert len(artifacts2) == 1
    assert artifacts2[0]["file_path"] == "/tmp/b1.log"


def test_update_artifact_kind(db_path: Path) -> None:
    """UPDATE: изменить kind артефакта."""
    task = db.insert_task(db_path, title="Task")
    artifact = db.insert_artifact(
        db_path,
        task["id"],
        "/tmp/file.txt",
        "log",
    )

    updated = db.update_artifact(db_path, artifact["id"], kind="report")
    assert updated is not None
    assert updated["kind"] == "report"
    assert updated["file_path"] == "/tmp/file.txt"  # не изменился


def test_update_artifact_file_path(db_path: Path) -> None:
    """UPDATE: изменить file_path артефакта."""
    task = db.insert_task(db_path, title="Task")
    artifact = db.insert_artifact(
        db_path,
        task["id"],
        "/tmp/old_path.log",
        "log",
    )

    updated = db.update_artifact(db_path, artifact["id"], file_path="/tmp/new_path.log")
    assert updated is not None
    assert updated["file_path"] == "/tmp/new_path.log"
    assert updated["kind"] == "log"  # не изменился


def test_update_artifact_multiple_fields(db_path: Path) -> None:
    """UPDATE: изменить несколько полей одновременно."""
    task = db.insert_task(db_path, title="Task")
    artifact = db.insert_artifact(
        db_path,
        task["id"],
        "/tmp/old.log",
        "log",
    )

    updated = db.update_artifact(
        db_path,
        artifact["id"],
        kind="report",
        file_path="/tmp/new.pdf",
    )
    assert updated is not None
    assert updated["kind"] == "report"
    assert updated["file_path"] == "/tmp/new.pdf"


def test_update_artifact_invalid_field_ignored(db_path: Path) -> None:
    """UPDATE: игнорировать недопустимые поля."""
    task = db.insert_task(db_path, title="Task")
    artifact = db.insert_artifact(
        db_path,
        task["id"],
        "/tmp/file.log",
        "log",
    )

    updated = db.update_artifact(
        db_path,
        artifact["id"],
        invalid_field="ignored",
        task_id="should_not_change",
    )
    assert updated is not None
    assert updated["task_id"] == task["id"]  # не изменился


def test_update_artifact_not_found(db_path: Path) -> None:
    """UPDATE: вернуть None для несуществующего артефакта."""
    updated = db.update_artifact(db_path, 99999, kind="report")
    assert updated is None


def test_delete_artifact(db_path: Path) -> None:
    """DELETE: удалить артефакт."""
    task = db.insert_task(db_path, title="Task")
    artifact = db.insert_artifact(
        db_path,
        task["id"],
        "/tmp/file.log",
        "log",
    )

    deleted = db.delete_artifact(db_path, artifact["id"])
    assert deleted is True

    fetched = db.get_artifact(db_path, artifact["id"])
    assert fetched is None


def test_delete_artifact_not_found(db_path: Path) -> None:
    """DELETE: вернуть False если артефакта нет."""
    deleted = db.delete_artifact(db_path, 99999)
    assert deleted is False


def test_delete_artifact_doesnt_affect_other_artifacts(db_path: Path) -> None:
    """DELETE: удаление не влияет на другие артефакты."""
    task = db.insert_task(db_path, title="Task")
    a1 = db.insert_artifact(db_path, task["id"], "/tmp/a1.log", "log")
    a2 = db.insert_artifact(db_path, task["id"], "/tmp/a2.log", "log")

    db.delete_artifact(db_path, a1["id"])

    remaining = db.list_artifacts(db_path, task["id"])
    assert len(remaining) == 1
    assert remaining[0]["id"] == a2["id"]


def test_artifact_foreign_key_constraint(db_path: Path) -> None:
    """Тест внешнего ключа: нельзя добавить артефакт с несуществующим task_id."""
    with pytest.raises(sqlite3.IntegrityError):
        db.insert_artifact(
            db_path,
            task_id="nonexistent_task_id",
            file_path="/tmp/file.log",
            kind="log",
        )


def test_artifact_unique_constraint(db_path: Path) -> None:
    """Тест уникальности: нельзя добавить два артефакта с одинаковыми (task_id, file_path)."""
    task = db.insert_task(db_path, title="Task")
    db.insert_artifact(
        db_path,
        task["id"],
        "/tmp/same_path.log",
        "log",
    )

    with pytest.raises(sqlite3.IntegrityError):
        db.insert_artifact(
            db_path,
            task["id"],
            "/tmp/same_path.log",  # одинаковый путь
            "report",
        )


def test_artifact_indexes_exist(db_path: Path) -> None:
    """Проверить, что созданы индексы на task_id и created_at."""
    conn = sqlite3.connect(db_path)
    try:
        indexes = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='task_artifacts'"
        )}
    finally:
        conn.close()

    assert "idx_artifacts_task" in indexes
    assert "idx_artifacts_created" in indexes


def test_task_artifacts_relationship(db_path: Path) -> None:
    """Проверить отношение many-to-one: несколько артефактов → одна задача."""
    task = db.insert_task(db_path, title="Task")

    artifacts = []
    for i in range(3):
        a = db.insert_artifact(
            db_path,
            task["id"],
            f"/tmp/file{i}.log",
            "log",
        )
        artifacts.append(a)

    # Все артефакты связаны с одной задачей
    listed = db.list_artifacts(db_path, task["id"])
    assert len(listed) == 3
    for artifact in listed:
        assert artifact["task_id"] == task["id"]


def test_artifact_table_exists(db_path: Path) -> None:
    """Проверить, что таблица task_artifacts создана в БД."""
    conn = sqlite3.connect(db_path)
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    finally:
        conn.close()

    assert "task_artifacts" in tables

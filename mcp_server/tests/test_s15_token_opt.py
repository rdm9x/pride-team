"""Тесты S15.2 — ADR-006: token optimization quick wins.

Покрывает:
  1. chat_recent default limit = 10 (было 50).
  2. model_hint: create_task сохраняет hint, get_task возвращает, update_task меняет.
  3. list_tasks включает model_hint в ответ.
  4. Обратная совместимость: create_task без model_hint → model_hint=None.
  5. update_task с model_hint=None не меняет существующий hint (не перетирает).
  6. Миграционная функция _add_column_if_missing идемпотентна.
"""

from __future__ import annotations

import inspect
import sqlite3
from pathlib import Path

import pytest

from pride_tasks import db, tools


# === 1. chat_recent default limit ===


def test_chat_recent_default_limit_is_10() -> None:
    """chat_recent должен иметь default limit=10 (ADR-006 §2.2)."""
    sig = inspect.signature(tools.chat_recent)
    assert sig.parameters["limit"].default == 10, (
        f"Ожидался default limit=10, получен {sig.parameters['limit'].default}"
    )


def test_chat_recent_returns_only_limit_messages(db_path: Path) -> None:
    """chat_recent(limit=N) не должен возвращать больше N сообщений."""
    for i in range(15):
        tools.chat_post("тимлид", f"msg {i}", db_path=db_path)

    res = tools.chat_recent(db_path=db_path)  # default limit=10
    assert res["статус"] == "ok"
    assert res["всего"] <= 10


# === 2. model_hint — create_task ===


def test_create_task_with_model_hint(db_path: Path) -> None:
    """create_task сохраняет model_hint в БД."""
    res = tools.create_task(title="Архитектурное ADR", model_hint="opus", db_path=db_path)
    assert res["статус"] == "ok"
    assert res["задача"]["model_hint"] == "opus"


def test_create_task_without_model_hint_is_none(db_path: Path) -> None:
    """create_task без model_hint → model_hint=None (backward compat)."""
    res = tools.create_task(title="Простая задача", db_path=db_path)
    assert res["статус"] == "ok"
    assert res["задача"]["model_hint"] is None


def test_create_task_model_hint_haiku(db_path: Path) -> None:
    """create_task с model_hint='haiku' сохраняется корректно."""
    res = tools.create_task(title="Тривиальная", model_hint="haiku", db_path=db_path)
    assert res["статус"] == "ok"
    assert res["задача"]["model_hint"] == "haiku"


# === 3. get_task включает model_hint ===


def test_get_task_returns_model_hint(db_path: Path) -> None:
    """get_task возвращает model_hint в ответе."""
    created = tools.create_task(title="Задача с хинтом", model_hint="sonnet", db_path=db_path)
    task_id = created["задача"]["id"]

    res = tools.get_task(task_id, db_path=db_path)
    assert res["статус"] == "ok"
    assert res["задача"]["model_hint"] == "sonnet"


def test_get_task_model_hint_none_when_not_set(db_path: Path) -> None:
    """get_task возвращает model_hint=None когда не задан."""
    created = tools.create_task(title="Без хинта", db_path=db_path)
    task_id = created["задача"]["id"]

    res = tools.get_task(task_id, db_path=db_path)
    assert res["статус"] == "ok"
    assert res["задача"]["model_hint"] is None


# === 4. update_task с model_hint ===


def test_update_task_sets_model_hint(db_path: Path) -> None:
    """update_task может выставить model_hint задаче."""
    created = tools.create_task(title="Задача", db_path=db_path)
    task_id = created["задача"]["id"]
    assert created["задача"]["model_hint"] is None

    res = tools.update_task(task_id, model_hint="opus", db_path=db_path)
    assert res["статус"] == "ok"
    assert res["задача"]["model_hint"] == "opus"


def test_update_task_changes_model_hint(db_path: Path) -> None:
    """update_task может изменить уже выставленный model_hint."""
    created = tools.create_task(title="Задача", model_hint="opus", db_path=db_path)
    task_id = created["задача"]["id"]

    res = tools.update_task(task_id, model_hint="haiku", db_path=db_path)
    assert res["статус"] == "ok"
    assert res["задача"]["model_hint"] == "haiku"


def test_update_task_without_model_hint_preserves_existing(db_path: Path) -> None:
    """update_task без явного model_hint не перетирает существующий hint."""
    created = tools.create_task(title="Задача", model_hint="opus", db_path=db_path)
    task_id = created["задача"]["id"]

    # Обновляем только status — model_hint не передаём
    res = tools.update_task(task_id, status="wip", db_path=db_path)
    assert res["статус"] == "ok"
    assert res["задача"]["model_hint"] == "opus", (
        "model_hint должен остаться 'opus' после update_task без явного model_hint"
    )


# === 5. list_tasks включает model_hint ===


def test_list_tasks_includes_model_hint(db_path: Path) -> None:
    """list_tasks включает model_hint в каждую задачу."""
    tools.create_task(title="С хинтом", model_hint="sonnet", db_path=db_path)
    tools.create_task(title="Без хинта", db_path=db_path)

    res = tools.list_tasks(db_path=db_path)
    assert res["статус"] == "ok"
    assert res["всего"] == 2

    hints = {t["title"]: t.get("model_hint") for t in res["задачи"]}
    assert hints["С хинтом"] == "sonnet"
    assert hints["Без хинта"] is None


# === 6. Миграция idempotent ===


def test_add_column_if_missing_idempotent(tmp_path: Path) -> None:
    """_add_column_if_missing безопасно вызывать несколько раз."""
    db_path = tmp_path / "tasks.db"
    db.init_db(db_path)

    conn = sqlite3.connect(db_path)
    try:
        # Первый вызов — колонка уже должна быть (init_db добавляет через ensure_dev_department)
        db._add_column_if_missing(conn, "tasks", "model_hint", "TEXT")
        # Второй вызов — не должен бросать ошибку
        db._add_column_if_missing(conn, "tasks", "model_hint", "TEXT")

        existing = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
        assert "model_hint" in existing
    finally:
        conn.close()


def test_model_hint_column_exists_after_init_db(tmp_path: Path) -> None:
    """После init_db колонка model_hint должна существовать в таблице tasks."""
    db_path = tmp_path / "tasks.db"
    db.init_db(db_path)

    conn = sqlite3.connect(db_path)
    try:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
        assert "model_hint" in existing, "model_hint должна быть в схеме после init_db"
    finally:
        conn.close()


# === 7. Полный round-trip ===


def test_model_hint_full_roundtrip(db_path: Path) -> None:
    """create → get → update → get — полный цикл model_hint."""
    # create с hint
    created = tools.create_task(title="Round-trip", model_hint="haiku", db_path=db_path)
    tid = created["задача"]["id"]
    assert created["задача"]["model_hint"] == "haiku"

    # get
    got = tools.get_task(tid, db_path=db_path)
    assert got["задача"]["model_hint"] == "haiku"

    # update hint
    updated = tools.update_task(tid, model_hint="opus", db_path=db_path)
    assert updated["задача"]["model_hint"] == "opus"

    # get после update
    got2 = tools.get_task(tid, db_path=db_path)
    assert got2["задача"]["model_hint"] == "opus"

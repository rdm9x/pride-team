"""Phase 3a (B1) — Migration smoke: chat_threads + thread_id в chat_messages.

Цель: убедиться что миграция создаёт chat_threads, добавляет thread_id в chat_messages,
создаёт default-thread и привязывает все existing messages к нему без потери данных.

Сценарий теста:
  1. Создать тестовую БД с existing chat_messages (без thread_id).
  2. Зафиксировать «before» counts.
  3. Запустить `scripts/migrate_chat_threads.py` через subprocess
     (с DEVBOARD_TASKS_DB → tmp_path/tasks.db).
  4. Verify:
     - таблица chat_threads создана;
     - индексы созданы;
     - колонка thread_id добавлена в chat_messages;
     - default-thread существует с id='default', title='📌 General', kind='direct';
     - все existing chat_messages получили thread_id='default';
     - никакие messages не потеряны;
  5. Idempotency: запустить миграцию повторно — ничего не меняется.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION_SCRIPT = _REPO_ROOT / "scripts" / "migrate_chat_threads.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _table_count(conn: sqlite3.Connection, table: str) -> int:
    """Считает COUNT(*) для таблицы. Если таблицы нет — возвращает 0."""
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except sqlite3.OperationalError:
        return 0


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    """True, если таблица существует."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """True, если колонка существует в таблице."""
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    return column in columns


def _index_exists(conn: sqlite3.Connection, name: str) -> bool:
    """True, если индекс существует."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _run_migration(db_path: Path) -> subprocess.CompletedProcess[str]:
    """Запустить migrate_chat_threads.py в subprocess. Возвращает результат."""
    env = os.environ.copy()
    env["DEVBOARD_TASKS_DB"] = str(db_path)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(_MIGRATION_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
    )


def _run_check(db_path: Path) -> subprocess.CompletedProcess[str]:
    """Запустить migrate_chat_threads.py --check."""
    env = os.environ.copy()
    env["DEVBOARD_TASKS_DB"] = str(db_path)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(_MIGRATION_SCRIPT), "--check"],
        env=env,
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_with_messages(tmp_path: Path) -> Path:
    """Тестовая БД с existing chat_messages (без thread_id).

    Схема берётся из SCHEMA_SQL, но chat_threads и thread_id исключаются.
    """
    db_path = tmp_path / "tasks.db"

    # Минимальная схема pre-migration.
    pre_schema_sql = """
CREATE TABLE departments (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  description TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL,
  archived_at INTEGER
);

CREATE TABLE chat_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  author TEXT NOT NULL,
  text TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  department_id TEXT REFERENCES departments(id)
);

CREATE INDEX idx_chat_created ON chat_messages(created_at);
"""

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(pre_schema_sql)

        # Вставляем test-department.
        conn.execute(
            "INSERT INTO departments (id, name, created_at) VALUES (?, ?, ?)",
            ("dev", "Dev", 1000),
        )

        # Вставляем test-messages (без thread_id).
        conn.execute(
            "INSERT INTO chat_messages (author, text, created_at, department_id) "
            "VALUES (?, ?, ?, ?)",
            ("тимлид", "Первое сообщение", 1100, "dev"),
        )
        conn.execute(
            "INSERT INTO chat_messages (author, text, created_at, department_id) "
            "VALUES (?, ?, ?, ?)",
            ("бэкенд", "Второе сообщение", 1200, "dev"),
        )
        conn.execute(
            "INSERT INTO chat_messages (author, text, created_at, department_id) "
            "VALUES (?, ?, ?, ?)",
            ("qa", "Третье сообщение", 1300, "dev"),
        )

        conn.commit()
    finally:
        conn.close()

    return db_path


# ---------------------------------------------------------------------------
# Pre-condition tests
# ---------------------------------------------------------------------------


def test_pre_migration_no_chat_threads(db_with_messages: Path) -> None:
    """Sanity: тестовая БД не содержит chat_threads и thread_id."""
    conn = sqlite3.connect(db_with_messages)
    try:
        assert not _table_exists(conn, "chat_threads"), \
            "Pre-migration БД не должна иметь таблицу chat_threads"

        assert not _column_exists(conn, "chat_messages", "thread_id"), \
            "Pre-migration БД не должна иметь thread_id в chat_messages"

        # Но должны быть messages.
        assert _table_count(conn, "chat_messages") == 3, \
            "Pre-migration БД должна иметь 3 test-сообщения"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Главный сценарий: миграция создаёт chat_threads и backfill
# ---------------------------------------------------------------------------


def test_migration_creates_chat_threads(db_with_messages: Path) -> None:
    """Миграция создаёт таблицу chat_threads с индексами."""
    result = _run_migration(db_with_messages)
    assert result.returncode == 0, (
        f"Миграция упала. stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    conn = sqlite3.connect(db_with_messages)
    try:
        assert _table_exists(conn, "chat_threads"), "Таблица chat_threads не создана"
        assert _index_exists(conn, "idx_chat_thread_created"), \
            "Индекс idx_chat_thread_created не создан"
        assert _index_exists(conn, "idx_chat_thread_status"), \
            "Индекс idx_chat_thread_status не создан"
    finally:
        conn.close()


def test_migration_adds_thread_id_column(db_with_messages: Path) -> None:
    """Миграция добавляет колонку thread_id в chat_messages."""
    result = _run_migration(db_with_messages)
    assert result.returncode == 0

    conn = sqlite3.connect(db_with_messages)
    try:
        assert _column_exists(conn, "chat_messages", "thread_id"), \
            "Колонка thread_id не добавлена в chat_messages"
        assert _index_exists(conn, "idx_chat_messages_thread"), \
            "Индекс idx_chat_messages_thread не создан"
    finally:
        conn.close()


def test_migration_creates_default_thread(db_with_messages: Path) -> None:
    """Миграция создаёт default-thread с правильными параметрами."""
    result = _run_migration(db_with_messages)
    assert result.returncode == 0

    conn = sqlite3.connect(db_with_messages)
    conn.row_factory = sqlite3.Row
    try:
        default_thread = conn.execute(
            "SELECT id, title, kind, status FROM chat_threads WHERE id=?",
            ("default",),
        ).fetchone()
        assert default_thread is not None, "Default-thread не создан"
        assert default_thread["title"] == "📌 General", f"Неправильный title: {default_thread['title']}"
        assert default_thread["kind"] == "direct", f"Неправильный kind: {default_thread['kind']}"
        assert default_thread["status"] == "active", f"Неправильный status: {default_thread['status']}"
    finally:
        conn.close()


def test_migration_backfill_messages_to_default(db_with_messages: Path) -> None:
    """Миграция привязывает existing messages к default-thread."""
    # Count before.
    conn_before = sqlite3.connect(db_with_messages)
    try:
        before_count = _table_count(conn_before, "chat_messages")
        before_ids = {r[0] for r in conn_before.execute("SELECT id FROM chat_messages")}
    finally:
        conn_before.close()

    result = _run_migration(db_with_messages)
    assert result.returncode == 0

    conn_after = sqlite3.connect(db_with_messages)
    conn_after.row_factory = sqlite3.Row
    try:
        # Count после.
        after_count = _table_count(conn_after, "chat_messages")
        assert after_count == before_count, "Messages потеряны или дублированы"

        # Все messages имеют thread_id='default'.
        bad_messages = conn_after.execute(
            "SELECT id FROM chat_messages WHERE thread_id != 'default' OR thread_id IS NULL"
        ).fetchall()
        assert not bad_messages, f"Найдены messages без thread_id='default': {[r[0] for r in bad_messages]}"

        # Те же IDs, что и раньше.
        after_ids = {r[0] for r in conn_after.execute("SELECT id FROM chat_messages")}
        assert after_ids == before_ids, "Набор message-IDs изменился"

        # Все 3 test-messages связаны с default-thread.
        three_messages = conn_after.execute(
            "SELECT id, author, text, thread_id FROM chat_messages ORDER BY id"
        ).fetchall()
        assert len(three_messages) == 3
        for msg in three_messages:
            assert msg["thread_id"] == "default", (
                f"Message {msg['id']} не связана с default-thread"
            )
    finally:
        conn_after.close()


def test_migration_no_data_loss(db_with_messages: Path) -> None:
    """Миграция не теряет данные сообщений (author, text, created_at, department_id)."""
    # Before.
    conn_before = sqlite3.connect(db_with_messages)
    conn_before.row_factory = sqlite3.Row
    try:
        before_messages = conn_before.execute(
            "SELECT id, author, text, created_at, department_id FROM chat_messages ORDER BY id"
        ).fetchall()
        before_data = [dict(r) for r in before_messages]
    finally:
        conn_before.close()

    result = _run_migration(db_with_messages)
    assert result.returncode == 0

    # After.
    conn_after = sqlite3.connect(db_with_messages)
    conn_after.row_factory = sqlite3.Row
    try:
        after_messages = conn_after.execute(
            "SELECT id, author, text, created_at, department_id FROM chat_messages ORDER BY id"
        ).fetchall()
        after_data = [dict(r) for r in after_messages]

        assert len(after_data) == len(before_data)
        for before_msg, after_msg in zip(before_data, after_data):
            # Проверяем что основные поля не изменились.
            assert before_msg["id"] == after_msg["id"]
            assert before_msg["author"] == after_msg["author"]
            assert before_msg["text"] == after_msg["text"]
            assert before_msg["created_at"] == after_msg["created_at"]
            assert before_msg["department_id"] == after_msg["department_id"]
    finally:
        conn_after.close()


# ---------------------------------------------------------------------------
# Идемпотентность
# ---------------------------------------------------------------------------


def test_migration_is_idempotent(db_with_messages: Path) -> None:
    """Повторный запуск миграции ничего не меняет и не дублирует."""
    # Первый прогон.
    result1 = _run_migration(db_with_messages)
    assert result1.returncode == 0

    conn = sqlite3.connect(db_with_messages)
    try:
        after_1_messages = _table_count(conn, "chat_messages")
        after_1_threads = _table_count(conn, "chat_threads")
    finally:
        conn.close()

    # Второй прогон.
    result2 = _run_migration(db_with_messages)
    assert result2.returncode == 0
    # Скрипт должен сообщить что миграция уже выполнена.
    assert "уже существуют" in (result2.stdout + result2.stderr), (
        f"Повторный запуск не задетектил что миграция выполнена.\n"
        f"stdout: {result2.stdout}\nstderr: {result2.stderr}"
    )

    conn = sqlite3.connect(db_with_messages)
    try:
        after_2_messages = _table_count(conn, "chat_messages")
        after_2_threads = _table_count(conn, "chat_threads")

        assert after_1_messages == after_2_messages, "Messages дублированы между прогонами"
        assert after_1_threads == after_2_threads, "Threads дублированы между прогонами"

        # Default-thread не задвоен.
        default_count = conn.execute(
            "SELECT COUNT(*) FROM chat_threads WHERE id='default'"
        ).fetchone()[0]
        assert default_count == 1, f"Default-thread задвоен: count={default_count}"
    finally:
        conn.close()


def test_migration_check_flag(db_with_messages: Path) -> None:
    """Флаг --check только проверяет статус без изменений."""
    # До миграции.
    result_before = _run_check(db_with_messages)
    assert result_before.returncode == 1, "До миграции --check должен вернуть 1 (объекты отсутствуют)"

    # Запускаем полную миграцию.
    result = _run_migration(db_with_messages)
    assert result.returncode == 0

    # После миграции.
    result_after = _run_check(db_with_messages)
    assert result_after.returncode == 0, "После миграции --check должен вернуть 0 (объекты есть)"


def test_migration_third_run_stable(db_with_messages: Path) -> None:
    """Третий и любой последующий запуск ничего не меняет."""
    for i in range(3):
        result = _run_migration(db_with_messages)
        assert result.returncode == 0, f"Прогон {i+1} упал"

    conn = sqlite3.connect(db_with_messages)
    try:
        # Все messages связаны с default-thread.
        default_linked = conn.execute(
            "SELECT COUNT(*) FROM chat_messages WHERE thread_id='default'"
        ).fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0]
        assert default_linked == total == 3
    finally:
        conn.close()


def test_migration_backup_created(db_with_messages: Path) -> None:
    """Миграция создаёт backup-файл перед изменениями."""
    backup_dir = db_with_messages.parent

    # До миграции.
    backups_before = list(backup_dir.glob("tasks.db.bak.*"))

    result = _run_migration(db_with_messages)
    assert result.returncode == 0

    # После миграции.
    backups_after = list(backup_dir.glob("tasks.db.bak.*"))
    assert len(backups_after) > len(backups_before), \
        "Backup-файл не был создан"

    # Новый backup должен быть валидный SQLite.
    new_backup = (set(backups_after) - set(backups_before)).pop()
    backup_conn = sqlite3.connect(new_backup)
    try:
        # Проверяем что это pre-migration состояние (без thread_id).
        cols = {row[1] for row in backup_conn.execute("PRAGMA table_info(chat_messages)")}
        assert "thread_id" not in cols, "Backup содержит post-migration схему (должна быть pre-migration)"
    finally:
        backup_conn.close()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_migration_with_empty_messages(tmp_path: Path) -> None:
    """Миграция работает с пустой таблицей chat_messages."""
    db_path = tmp_path / "tasks.db"

    # Только departments и chat_messages (без сообщений).
    schema_sql = """
CREATE TABLE departments (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  description TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL,
  archived_at INTEGER
);

CREATE TABLE chat_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  author TEXT NOT NULL,
  text TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  department_id TEXT REFERENCES departments(id)
);

CREATE INDEX idx_chat_created ON chat_messages(created_at);
"""

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(schema_sql)
        conn.execute(
            "INSERT INTO departments (id, name, created_at) VALUES (?, ?, ?)",
            ("dev", "Dev", 1000),
        )
    finally:
        conn.close()

    result = _run_migration(db_path)
    assert result.returncode == 0, (
        f"Миграция не работает с пустой chat_messages. "
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    # Default-thread всё равно должен быть создан.
    conn = sqlite3.connect(db_path)
    try:
        default = conn.execute(
            "SELECT COUNT(*) FROM chat_threads WHERE id='default'"
        ).fetchone()[0]
        assert default == 1
    finally:
        conn.close()


def test_migration_default_thread_participants_is_json_array(db_with_messages: Path) -> None:
    """Default-thread имеет participants как JSON-array (для совместимости)."""
    result = _run_migration(db_with_messages)
    assert result.returncode == 0

    conn = sqlite3.connect(db_with_messages)
    try:
        thread = conn.execute(
            "SELECT participants FROM chat_threads WHERE id='default'"
        ).fetchone()
        participants = json.loads(thread[0])
        assert isinstance(participants, list), f"participants не JSON-array: {thread[0]}"
    finally:
        conn.close()


def test_migration_chat_threads_has_all_fields_adr011(db_with_messages: Path) -> None:
    """ADR-011 §2.3: chat_threads имеет все поля из спецификации."""
    result = _run_migration(db_with_messages)
    assert result.returncode == 0

    conn = sqlite3.connect(db_with_messages)
    try:
        # Проверяем что все поля существуют.
        columns = {row[1] for row in conn.execute("PRAGMA table_info(chat_threads)")}
        required_columns = {
            "id", "title", "kind", "participants", "status",
            "created_at", "updated_at", "finished_at",
            "source_problem", "decision_summary", "decision_approved_at", "decision_created_tasks",
            "rounds_planned"
        }
        missing = required_columns - columns
        assert not missing, f"Отсутствуют колонки: {missing}"
    finally:
        conn.close()


def test_migration_chat_threads_kind_check_constraint(db_with_messages: Path) -> None:
    """chat_threads.kind имеет CHECK constraint ('direct' или 'planning')."""
    result = _run_migration(db_with_messages)
    assert result.returncode == 0

    conn = sqlite3.connect(db_with_messages)
    try:
        # Попытка вставить невалидное значение должна упасть.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO chat_threads
                (id, title, kind, participants, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                ("test", "Test", "invalid_kind", "[]", "active", 1000, 1000),
            )
            conn.commit()
    finally:
        conn.close()


def test_migration_chat_threads_status_check_constraint(db_with_messages: Path) -> None:
    """chat_threads.status имеет CHECK constraint ('active', 'finished', 'archived', 'aborted')."""
    result = _run_migration(db_with_messages)
    assert result.returncode == 0

    conn = sqlite3.connect(db_with_messages)
    try:
        # Попытка вставить невалидное значение должна упасть.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO chat_threads
                (id, title, kind, participants, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                ("test", "Test", "direct", "[]", "invalid_status", 1000, 1000),
            )
            conn.commit()
    finally:
        conn.close()


def test_migration_default_thread_has_updated_at(db_with_messages: Path) -> None:
    """Default-thread имеет updated_at равно created_at при создании."""
    result = _run_migration(db_with_messages)
    assert result.returncode == 0

    conn = sqlite3.connect(db_with_messages)
    conn.row_factory = sqlite3.Row
    try:
        thread = conn.execute(
            "SELECT created_at, updated_at FROM chat_threads WHERE id='default'"
        ).fetchone()
        assert thread is not None
        assert thread["created_at"] == thread["updated_at"], \
            "Default-thread updated_at должен быть равен created_at"
    finally:
        conn.close()


def test_migration_index_chat_threads_updated_exists(db_with_messages: Path) -> None:
    """Индекс idx_chat_threads_updated создан для сортировки по updated_at DESC."""
    result = _run_migration(db_with_messages)
    assert result.returncode == 0

    conn = sqlite3.connect(db_with_messages)
    try:
        assert _index_exists(conn, "idx_chat_threads_updated"), \
            "Индекс idx_chat_threads_updated не создан"
    finally:
        conn.close()


def test_migration_chat_threads_accepts_all_valid_statuses(db_with_messages: Path) -> None:
    """chat_threads.status принимает все валидные значения: 'active', 'finished', 'archived', 'aborted'."""
    result = _run_migration(db_with_messages)
    assert result.returncode == 0

    conn = sqlite3.connect(db_with_messages)
    try:
        # Все валидные статусы должны быть приняты.
        for status in ["active", "finished", "archived", "aborted"]:
            conn.execute(
                """
                INSERT INTO chat_threads
                (id, title, kind, participants, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (f"test_{status}", f"Test {status}", "direct", "[]", status, 1000, 1000),
            )
        conn.commit()

        # Проверяем что все вставились.
        count = conn.execute("SELECT COUNT(*) FROM chat_threads WHERE id LIKE 'test_%'").fetchone()[0]
        assert count == 4, f"Не все статусы были вставлены: {count}"
    finally:
        conn.close()

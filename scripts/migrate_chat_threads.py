#!/usr/bin/env python3
"""Миграция Phase 3a (B1) — chat_threads + thread_id в chat_messages.

DDL:
- `chat_threads` таблица с fields: id, title, kind, participants, status,
  created_at, finished_at, decision, rounds_planned, current_round
- ALTER TABLE chat_messages ADD COLUMN thread_id TEXT REFERENCES chat_threads(id)
- CREATE INDEX idx_chat_thread_created ON chat_threads(created_at)
- CREATE INDEX idx_chat_messages_thread ON chat_messages(thread_id)

Backfill:
- Создаёт default-thread с id='default', title='📌 General', kind='direct'
- Все существующие chat_messages получают thread_id='default'

Использование::

    python scripts/migrate_chat_threads.py              # запустить миграцию
    python scripts/migrate_chat_threads.py --check      # только проверить статус
    python scripts/migrate_chat_threads.py --db PATH    # явный путь к БД

ENV:
    DEVBOARD_TASKS_DB — переопределяет путь к tasks.db.

Идемпотентно: все CREATE — через IF NOT EXISTS, безопасно запускать многократно.
Pre-flight backup: создаёт ``tasks.db.bak.<timestamp>`` перед изменениями.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

# Подключаем путь к пакету (если запускаем из корня репо без установки).
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "mcp_server"))

try:
    from devboard_tasks.db import default_db_path  # type: ignore
except ImportError:
    def default_db_path() -> Path:  # type: ignore[misc]
        return _REPO_ROOT / "data" / "tasks.db"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("migrate_chat_threads")


# === DDL ===

CHAT_THREADS_SQL = """
CREATE TABLE IF NOT EXISTS chat_threads (
  id              TEXT PRIMARY KEY,
  title           TEXT NOT NULL,
  kind            TEXT NOT NULL DEFAULT 'direct',
  participants    TEXT NOT NULL DEFAULT '[]',
  status          TEXT NOT NULL DEFAULT 'active',
  created_at      INTEGER NOT NULL,
  finished_at     INTEGER,
  decision        TEXT,
  rounds_planned  INTEGER,
  current_round   INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_chat_thread_created
  ON chat_threads(created_at);

CREATE INDEX IF NOT EXISTS idx_chat_thread_status
  ON chat_threads(status) WHERE finished_at IS NULL;
"""

# Добавляем thread_id в chat_messages (если уже нет).
ADD_THREAD_ID_SQL = """
ALTER TABLE chat_messages ADD COLUMN thread_id TEXT REFERENCES chat_threads(id);
"""

# Индекс на thread_id для быстрых запросов.
THREAD_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_chat_messages_thread
  ON chat_messages(thread_id);
"""

# Объекты, которые миграция должна создать (для sanity-check).
_EXPECTED_OBJECTS: tuple[tuple[str, str], ...] = (
    ("table", "chat_threads"),
    ("index", "idx_chat_thread_created"),
    ("index", "idx_chat_thread_status"),
    ("index", "idx_chat_messages_thread"),
)


# === Helpers ===


def _get_db_path() -> Path:
    """Путь к БД: --db > DEVBOARD_TASKS_DB > default."""
    env = os.environ.get("DEVBOARD_TASKS_DB")
    if env:
        return Path(env)
    return default_db_path()


def _object_exists(conn: sqlite3.Connection, obj_type: str, name: str) -> bool:
    """True, если объект (table/index/trigger) уже есть в sqlite_master."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type=? AND name=?",
        (obj_type, name),
    ).fetchone()
    return row is not None


def _all_objects_present(conn: sqlite3.Connection) -> bool:
    """Все ожидаемые объекты уже существуют?"""
    return all(_object_exists(conn, t, n) for t, n in _EXPECTED_OBJECTS)


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """True, если колонка существует в таблице."""
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    return column in columns


def _make_backup(db_path: Path) -> Path:
    """Создаёт tasks.db.bak.<unix-ts>; возвращает путь к копии."""
    ts = int(time.time())
    backup_path = db_path.parent / f"{db_path.name}.bak.{ts}"
    shutil.copy2(db_path, backup_path)
    return backup_path


# === Main migration ===


def migrate(db_path: Path) -> int:
    """Применить миграцию. Возвращает 0 при успехе, 1 при ошибке."""

    if not db_path.exists():
        log.error("БД не найдена: %s", db_path)
        return 1

    # Pre-check — может уже всё на месте.
    pre_conn = sqlite3.connect(db_path)
    try:
        already_done = _all_objects_present(pre_conn)
    finally:
        pre_conn.close()

    if already_done:
        log.info(
            "Все объекты Phase 3a (chat_threads) уже существуют — миграция не нужна (идемпотентный no-op)."
        )
        return 0

    # Pre-flight backup.
    try:
        backup_path = _make_backup(db_path)
        log.info("Backup создан: %s", backup_path)
    except OSError as exc:
        log.error("Не удалось создать backup: %s", exc)
        return 1

    conn = sqlite3.connect(db_path)
    try:
        # WAL + FK on.
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")

        now = int(time.time())

        log.info("Создаю таблицу chat_threads + индексы ...")
        conn.executescript(CHAT_THREADS_SQL)

        # Создаём default-thread.
        log.info("Создаю default-thread ...")
        try:
            conn.execute(
                """
                INSERT INTO chat_threads (id, title, kind, participants, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("default", "📌 General", "direct", json.dumps([]), "active", now),
            )
        except sqlite3.IntegrityError:
            # Default thread уже есть.
            log.info("Default-thread уже существует, пропускаем вставку.")

        # Добавляем thread_id в chat_messages (если колонки ещё нет).
        log.info("Проверяю наличие колонки thread_id в chat_messages ...")
        if not _column_exists(conn, "chat_messages", "thread_id"):
            log.info("Добавляю колонку thread_id в chat_messages ...")
            conn.execute(ADD_THREAD_ID_SQL)
        else:
            log.info("Колонка thread_id уже существует в chat_messages.")

        # Создаём индекс.
        log.info("Создаю индекс на chat_messages(thread_id) ...")
        conn.executescript(THREAD_INDEX_SQL)

        # Backfill: все existing messages получают thread_id='default'.
        log.info("Backfill: привязываю существующие сообщения к default-thread ...")
        conn.execute(
            "UPDATE chat_messages SET thread_id = ? WHERE thread_id IS NULL",
            ("default",),
        )
        affected = conn.total_changes
        log.info("Backfill завершён: %d сообщений обновлено.", affected)

        # Sanity-check: SELECT из новых таблиц.
        log.info("Sanity-check: SELECT из новых таблиц ...")
        conn.execute("SELECT 1 FROM chat_threads LIMIT 1")
        conn.execute("SELECT 1 FROM chat_messages LIMIT 1")

        # Проверим что default-thread есть.
        default_thread = conn.execute(
            "SELECT id, title FROM chat_threads WHERE id = ?",
            ("default",),
        ).fetchone()
        if not default_thread:
            log.error("Default-thread не найден после вставки!")
            return 1
        log.info("✓ Default-thread найден: id=%s, title=%s", default_thread[0], default_thread[1])

        # Проверим что все ожидаемые объекты теперь существуют.
        missing = [
            (t, n) for t, n in _EXPECTED_OBJECTS
            if not _object_exists(conn, t, n)
        ]
        if missing:
            log.error("Не все объекты созданы: %s", missing)
            return 1

        conn.commit()
        log.info("Миграция Phase 3a (chat_threads) завершена успешно.")
        log.info("Backup: %s", backup_path)
        return 0

    except Exception as exc:  # noqa: BLE001 — логируем подробно
        log.exception("Ошибка миграции: %s", exc)
        log.error(
            "Восстановите из backup при необходимости: %s",
            backup_path,
        )
        return 1
    finally:
        conn.close()


def check(db_path: Path) -> int:
    """Только проверить наличие всех объектов. 0 если есть, 1 если нет."""
    if not db_path.exists():
        log.error("БД не найдена: %s", db_path)
        return 1
    conn = sqlite3.connect(db_path)
    try:
        missing: list[tuple[str, str]] = []
        for obj_type, name in _EXPECTED_OBJECTS:
            exists = _object_exists(conn, obj_type, name)
            log.info("%-8s %-40s %s", obj_type, name, "EXISTS" if exists else "MISSING")
            if not exists:
                missing.append((obj_type, name))

        # Проверим наличие thread_id в chat_messages.
        thread_id_exists = _column_exists(conn, "chat_messages", "thread_id")
        log.info("%-8s %-40s %s", "column", "chat_messages.thread_id", "EXISTS" if thread_id_exists else "MISSING")
        if not thread_id_exists:
            missing.append(("column", "chat_messages.thread_id"))

        # Проверим default-thread.
        default_thread = conn.execute(
            "SELECT id FROM chat_threads WHERE id = ?",
            ("default",),
        ).fetchone()
        log.info("%-8s %-40s %s", "data", "chat_threads.default", "EXISTS" if default_thread else "MISSING")
        if not default_thread:
            missing.append(("data", "chat_threads.default"))

        return 0 if not missing else 1
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 3a (B1) migration: chat_threads + thread_id в chat_messages."
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Путь к tasks.db (по умолчанию — из DEVBOARD_TASKS_DB или data/tasks.db)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Только проверить наличие новых объектов (без изменений).",
    )
    args = parser.parse_args()

    db_path = args.db if args.db else _get_db_path()
    log.info("БД: %s", db_path)

    if args.check:
        sys.exit(check(db_path))
    else:
        sys.exit(migrate(db_path))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Phase 3a B2 миграция — добавляем updated_at в chat_threads.

Этот скрипт добавляет:
- COLUMN updated_at в chat_threads (инициализируется как created_at)
- INDEX idx_chat_threads_updated (для сортировки в list_chat_threads)

Идемпотентно: все ALTER — через IF NOT EXISTS (где возможно).
"""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
from pathlib import Path

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
log = logging.getLogger("migrate_chat_threads_b2")


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


def _get_db_path() -> Path:
    """Путь к БД: DEVBOARD_TASKS_DB > default."""
    env = os.environ.get("DEVBOARD_TASKS_DB")
    if env:
        return Path(env)
    return default_db_path()


def migrate(db_path: Path) -> int:
    """Применить миграцию. Возвращает 0 при успехе, 1 при ошибке."""

    if not db_path.exists():
        log.error("БД не найдена: %s", db_path)
        return 1

    # Pre-check.
    pre_conn = sqlite3.connect(db_path)
    try:
        updated_at_exists = _column_exists(pre_conn, "chat_threads", "updated_at")
        idx_exists = _index_exists(pre_conn, "idx_chat_threads_updated")
    finally:
        pre_conn.close()

    if updated_at_exists and idx_exists:
        log.info("Миграция B2 уже применена (updated_at и индекс существуют) — no-op.")
        return 0

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")

        # Добавляем updated_at если его нет.
        if not updated_at_exists:
            log.info("Добавляю колонку updated_at в chat_threads...")
            try:
                # Инициализируем как created_at
                conn.execute(
                    "ALTER TABLE chat_threads ADD COLUMN updated_at INTEGER DEFAULT 0"
                )
                # Потом обновляем все существующие строки.
                conn.execute(
                    "UPDATE chat_threads SET updated_at = created_at WHERE updated_at = 0"
                )
            except sqlite3.OperationalError as e:
                log.warning(f"Колонка updated_at уже существует: {e}")

        # Добавляем индекс если его нет.
        if not idx_exists:
            log.info("Создаю индекс idx_chat_threads_updated...")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_threads_updated ON chat_threads(updated_at DESC)"
            )

        conn.commit()
        log.info("Миграция B2 завершена успешно.")
        return 0

    except Exception as exc:  # noqa: BLE001
        log.exception("Ошибка миграции: %s", exc)
        return 1
    finally:
        conn.close()


def check(db_path: Path) -> int:
    """Только проверить наличие полей. 0 если есть, 1 если нет."""
    if not db_path.exists():
        log.error("БД не найдена: %s", db_path)
        return 1

    conn = sqlite3.connect(db_path)
    try:
        updated_at_exists = _column_exists(conn, "chat_threads", "updated_at")
        idx_exists = _index_exists(conn, "idx_chat_threads_updated")

        log.info("%-8s %-40s %s", "column", "chat_threads.updated_at", "EXISTS" if updated_at_exists else "MISSING")
        log.info("%-8s %-40s %s", "index", "idx_chat_threads_updated", "EXISTS" if idx_exists else "MISSING")

        return 0 if (updated_at_exists and idx_exists) else 1
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 3a B2 migration: добавляем updated_at в chat_threads."
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

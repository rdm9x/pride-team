#!/usr/bin/env python3
"""Миграция S15.2 — ADR-006: добавить колонку model_hint в таблицу tasks.

Использование:
    python scripts/migrate_s15_model_hint.py              # запустить миграцию
    python scripts/migrate_s15_model_hint.py --check      # только проверить статус

Идемпотентно: безопасно запускать несколько раз.
Если колонка уже есть — завершается без изменений (код выхода 0).
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "mcp_server"))

try:
    from devboard_tasks.db import default_db_path
except ImportError:
    def default_db_path() -> Path:  # type: ignore[misc]
        return _REPO_ROOT / "data" / "tasks.db"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("migrate_s15_model_hint")


def _get_db_path() -> Path:
    import os
    env = os.environ.get("DEVBOARD_TASKS_DB")
    if env:
        return Path(env)
    return default_db_path()


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    return column in existing


def migrate(db_path: Path) -> int:
    """Добавляет model_hint TEXT в tasks. Возвращает 0 при успехе."""
    if not db_path.exists():
        log.error("БД не найдена: %s", db_path)
        return 1

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = OFF")

        if _column_exists(conn, "tasks", "model_hint"):
            log.info("Колонка tasks.model_hint уже существует — миграция не нужна.")
            return 0

        log.info("Добавляю колонку tasks.model_hint TEXT ...")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("ALTER TABLE tasks ADD COLUMN model_hint TEXT")
        conn.execute("COMMIT")
        log.info("Миграция S15.2 (model_hint) завершена успешно.")
        return 0

    except Exception as exc:
        log.exception("Ошибка миграции: %s", exc)
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        return 1
    finally:
        conn.close()


def check(db_path: Path) -> int:
    """Проверяет наличие колонки. Возвращает 0 если есть, 1 если нет."""
    if not db_path.exists():
        log.error("БД не найдена: %s", db_path)
        return 1
    conn = sqlite3.connect(db_path)
    try:
        exists = _column_exists(conn, "tasks", "model_hint")
        if exists:
            log.info("tasks.model_hint: EXISTS")
        else:
            log.info("tasks.model_hint: MISSING — запустите migrate_s15_model_hint.py")
        return 0 if exists else 1
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Миграция S15.2: добавить model_hint в tasks (ADR-006)."
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
        help="Только проверить наличие колонки (без изменений).",
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

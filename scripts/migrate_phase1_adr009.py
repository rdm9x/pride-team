#!/usr/bin/env python3
"""Миграция Phase 1 ADR-009 / ADR-007 — таблицы:

- `planning_sessions` + индекс `idx_planning_phase` (ADR-009 §2.4)
- `manager_chunks` + виртуальная `manager_fts` (FTS5) + 3 триггера sync
  + 2 индекса (user_source, updated) (ADR-007 §2.1)

Использование::

    python scripts/migrate_phase1_adr009.py              # запустить миграцию
    python scripts/migrate_phase1_adr009.py --check      # только проверить статус
    python scripts/migrate_phase1_adr009.py --db PATH    # явный путь к БД

ENV:
    DEVBOARD_TASKS_DB — переопределяет путь к tasks.db (как у других скриптов).

Идемпотентно: все CREATE — через IF NOT EXISTS, безопасно запускать многократно.
Pre-flight backup: создаёт ``tasks.db.bak.<timestamp>`` перед изменениями
(только когда реально есть что мигрировать, иначе пропускает).
"""

from __future__ import annotations

import argparse
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
log = logging.getLogger("migrate_phase1_adr009")


# === DDL ===
#
# Источники:
#   - ADR-009 §2.4 — planning_sessions + idx_planning_phase.
#   - ADR-007 §2.1 — manager_chunks + manager_fts + 3 триггера + 2 индекса.
#
# Все CREATE — через IF NOT EXISTS. SQLite поддерживает IF NOT EXISTS для
# TABLE / VIRTUAL TABLE / TRIGGER / INDEX, что делает миграцию идемпотентной.

PLANNING_SESSIONS_SQL = """
CREATE TABLE IF NOT EXISTS planning_sessions (
  id                    TEXT PRIMARY KEY,
  owner_request         TEXT NOT NULL,
  phase                 TEXT NOT NULL,
  departments_involved  TEXT NOT NULL,
  discussion_log        TEXT,
  consolidated_proposal TEXT,
  questions_for_owner   TEXT,
  owner_answer          TEXT,
  created_tasks         TEXT,
  started_at            INTEGER NOT NULL,
  finished_at           INTEGER
);

CREATE INDEX IF NOT EXISTS idx_planning_phase
  ON planning_sessions(phase) WHERE finished_at IS NULL;
"""

MANAGER_MEMORY_SQL = """
CREATE TABLE IF NOT EXISTS manager_chunks (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id      TEXT NOT NULL DEFAULT 'owner',
  source       TEXT NOT NULL,
  path         TEXT,
  start_line   INTEGER,
  end_line     INTEGER,
  text         TEXT NOT NULL,
  embedding    BLOB,
  tags         TEXT NOT NULL DEFAULT '[]',
  created_at   INTEGER NOT NULL,
  updated_at   INTEGER NOT NULL,
  archived_at  INTEGER
);

CREATE VIRTUAL TABLE IF NOT EXISTS manager_fts USING fts5(
  text,
  content='manager_chunks',
  content_rowid='id',
  tokenize='unicode61 remove_diacritics 1'
);

CREATE TRIGGER IF NOT EXISTS manager_chunks_ai
AFTER INSERT ON manager_chunks BEGIN
  INSERT INTO manager_fts(rowid, text) VALUES (new.id, new.text);
END;

CREATE TRIGGER IF NOT EXISTS manager_chunks_ad
AFTER DELETE ON manager_chunks BEGIN
  INSERT INTO manager_fts(manager_fts, rowid, text) VALUES('delete', old.id, old.text);
END;

CREATE TRIGGER IF NOT EXISTS manager_chunks_au
AFTER UPDATE ON manager_chunks BEGIN
  INSERT INTO manager_fts(manager_fts, rowid, text) VALUES('delete', old.id, old.text);
  INSERT INTO manager_fts(rowid, text) VALUES (new.id, new.text);
END;

CREATE INDEX IF NOT EXISTS idx_manager_chunks_user_source
  ON manager_chunks(user_id, source) WHERE archived_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_manager_chunks_updated
  ON manager_chunks(updated_at DESC) WHERE archived_at IS NULL;
"""

# Объекты, которые миграция должна создать (для sanity-check).
_EXPECTED_OBJECTS: tuple[tuple[str, str], ...] = (
    ("table",   "planning_sessions"),
    ("index",   "idx_planning_phase"),
    ("table",   "manager_chunks"),
    ("table",   "manager_fts"),         # virtual table тоже type='table'
    ("trigger", "manager_chunks_ai"),
    ("trigger", "manager_chunks_ad"),
    ("trigger", "manager_chunks_au"),
    ("index",   "idx_manager_chunks_user_source"),
    ("index",   "idx_manager_chunks_updated"),
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
            "Все объекты Phase-1 уже существуют — миграция не нужна (идемпотентный no-op)."
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
        # WAL + FK off на время DDL — таблицы создаются без ALTER TABLE, FK
        # ссылаются только сами на себя; отключаем для совместимости со
        # стилем других миграций (migrate_v2_departments).
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = OFF")

        log.info("Создаю planning_sessions + idx_planning_phase ...")
        conn.executescript(PLANNING_SESSIONS_SQL)

        log.info(
            "Создаю manager_chunks + manager_fts (FTS5) + 3 триггера + 2 индекса ..."
        )
        conn.executescript(MANAGER_MEMORY_SQL)

        # Sanity-check: SELECT 1 из новых таблиц.
        log.info("Sanity-check: SELECT из новых таблиц ...")
        conn.execute("SELECT 1 FROM planning_sessions LIMIT 1")
        conn.execute("SELECT 1 FROM manager_chunks LIMIT 1")
        conn.execute("SELECT 1 FROM manager_fts LIMIT 1")

        # Проверим что все ожидаемые объекты теперь существуют.
        missing = [
            (t, n) for t, n in _EXPECTED_OBJECTS
            if not _object_exists(conn, t, n)
        ]
        if missing:
            log.error("Не все объекты созданы: %s", missing)
            return 1

        log.info("Миграция Phase-1 ADR-009/ADR-007 завершена успешно.")
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
        return 0 if not missing else 1
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Phase-1 ADR-009/ADR-007 migration: planning_sessions + "
            "manager_chunks + manager_fts (FTS5) + триггеры + индексы."
        )
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

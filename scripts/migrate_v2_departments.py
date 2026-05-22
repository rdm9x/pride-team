#!/usr/bin/env python3
"""Миграция v2.0 — ADR-003: добавить таблицу departments в tasks.db.

Использование:
    python scripts/migrate_v2_departments.py              # запустить миграцию
    python scripts/migrate_v2_departments.py --rollback   # восстановить из .pre-v2.bak

Идемпотентно: безопасно запускать несколько раз.
Pre-flight: проверяет schema_meta.version на '== v2.0-departments' — если уже мигрировано,
завершается без изменений (код выхода 0).
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sqlite3
import sys
import time
from pathlib import Path

# Подключаем путь к пакету (если запускаем из корня репо без установки).
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "mcp_server"))

try:
    from pride_tasks.db import default_db_path
except ImportError:
    def default_db_path() -> Path:  # type: ignore[misc]
        return _REPO_ROOT / "data" / "tasks.db"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("migrate_v2_departments")

TARGET_VERSION = "v2.0-departments"
# Глобальные роли: не получают department_id.
_GLOBAL_ROLES = ("hr", "owner", "пользователь", "user")


def _get_db_path() -> Path:
    """Возвращает путь к tasks.db из переменной окружения или дефолтный."""
    import os
    env = os.environ.get("PRIDE_TASKS_DB")
    if env:
        return Path(env)
    return default_db_path()


def _schema_meta_version(conn: sqlite3.Connection) -> str | None:
    """Читает schema_meta.version из БД. Возвращает None если таблицы нет."""
    try:
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'version'"
        ).fetchone()
        return row[0] if row else None
    except sqlite3.OperationalError:
        return None


def _ensure_schema_meta(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_meta ("
        "  key TEXT PRIMARY KEY,"
        "  value TEXT NOT NULL"
        ")"
    )


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    return column in existing


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _index_exists(conn: sqlite3.Connection, index_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?", (index_name,)
    ).fetchone()
    return row is not None


def migrate(db_path: Path) -> int:
    """Выполняет миграцию. Возвращает 0 при успехе, 1 при ошибке."""
    if not db_path.exists():
        log.error("БД не найдена: %s", db_path)
        return 1

    backup_path = db_path.parent / f"{db_path.name}.pre-v2.bak"

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = OFF")  # Отключаем на время миграции.

    try:
        # Pre-flight: уже мигрировано?
        current_version = _schema_meta_version(conn)
        if current_version == TARGET_VERSION:
            log.info("Миграция уже выполнена (schema_meta.version=%s). Ничего не делаем.", TARGET_VERSION)
            return 0

        # Таблицы-источники должны существовать.
        for tbl in ("tasks", "roles", "chat_messages"):
            if not _table_exists(conn, tbl):
                log.error("Таблица %s не найдена — некорректная БД.", tbl)
                return 1

        conn.close()
        conn = None  # type: ignore[assignment]

        # Backup.
        log.info("Создаю резервную копию: %s → %s", db_path, backup_path)
        try:
            shutil.copy2(db_path, backup_path)
        except OSError as exc:
            log.error("Не удалось создать backup: %s", exc)
            return 1
        log.info("Backup создан успешно.")

        # Основная транзакция.
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = OFF")

        now = int(time.time())
        conn.execute("BEGIN IMMEDIATE")

        _ensure_schema_meta(conn)

        # Шаг 1: Создаём таблицу departments.
        if not _table_exists(conn, "departments"):
            log.info("Создаю таблицу departments...")
            conn.execute("""
                CREATE TABLE departments (
                  id            TEXT PRIMARY KEY,
                  name          TEXT NOT NULL UNIQUE,
                  description   TEXT NOT NULL DEFAULT '',
                  template_id   TEXT,
                  hr_session_id TEXT,
                  icon          TEXT DEFAULT '🗂',
                  created_at    INTEGER NOT NULL,
                  archived_at   INTEGER
                )
            """)
        else:
            log.info("Таблица departments уже существует — пропускаю создание.")

        # Шаг 2: Default department 'dev'.
        existing = conn.execute(
            "SELECT id FROM departments WHERE id = 'dev'"
        ).fetchone()
        if existing is None:
            log.info("Вставляю default department 'dev'.")
            conn.execute(
                "INSERT INTO departments (id, name, description, template_id, hr_session_id, icon, created_at) "
                "VALUES ('dev', 'Dev', 'Команда разработки devboard (мигрировано с v1.x)', NULL, NULL, '🛠', ?)",
                (now,),
            )
        else:
            log.info("Department 'dev' уже существует — пропускаю вставку.")

        # Шаг 3: ALTER TABLE tasks/roles/chat_messages.
        for table, col_def in [
            ("tasks",         "TEXT REFERENCES departments(id)"),
            ("roles",         "TEXT REFERENCES departments(id)"),
            ("chat_messages", "TEXT REFERENCES departments(id)"),
        ]:
            if not _column_exists(conn, table, "department_id"):
                log.info("ALTER TABLE %s ADD COLUMN department_id ...", table)
                conn.execute(f"ALTER TABLE {table} ADD COLUMN department_id {col_def}")
            else:
                log.info("Колонка %s.department_id уже существует — пропускаю.", table)

        # Шаг 4: Backfill tasks → 'dev'.
        updated = conn.execute(
            "UPDATE tasks SET department_id = 'dev' WHERE department_id IS NULL"
        ).rowcount
        log.info("Backfill tasks: %d строк обновлено.", updated)

        # Шаг 5: Backfill roles — НЕ-глобальные → 'dev'.
        placeholders = ",".join("?" * len(_GLOBAL_ROLES))
        updated = conn.execute(
            f"UPDATE roles SET department_id = 'dev' "
            f"WHERE department_id IS NULL AND name NOT IN ({placeholders})",
            _GLOBAL_ROLES,
        ).rowcount
        log.info("Backfill roles: %d строк обновлено.", updated)

        # Шаг 6: Backfill chat_messages → 'dev'.
        updated = conn.execute(
            "UPDATE chat_messages SET department_id = 'dev' WHERE department_id IS NULL"
        ).rowcount
        log.info("Backfill chat_messages: %d строк обновлено.", updated)

        # Шаг 7: Индексы.
        for idx, ddl in [
            ("idx_tasks_department",    "ON tasks(department_id)"),
            ("idx_tasks_dept_status",   "ON tasks(department_id, status)"),
            ("idx_roles_department",    "ON roles(department_id)"),
            ("idx_chat_messages_department", "ON chat_messages(department_id, created_at DESC)"),
        ]:
            if not _index_exists(conn, idx):
                log.info("Создаю индекс %s ...", idx)
                conn.execute(f"CREATE INDEX {idx} {ddl}")
            else:
                log.info("Индекс %s уже существует — пропускаю.", idx)

        # Шаг 8: Версия схемы.
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('version', ?)",
            (TARGET_VERSION,),
        )
        log.info("schema_meta.version установлена в '%s'.", TARGET_VERSION)

        conn.execute("COMMIT")
        log.info("Миграция v2.0-departments завершена успешно.")
        return 0

    except Exception as exc:
        log.exception("Ошибка миграции: %s. Откатываю транзакцию.", exc)
        if conn:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
        return 1
    finally:
        if conn:
            conn.close()


def rollback(db_path: Path) -> int:
    """Восстанавливает БД из .pre-v2.bak. Возвращает 0 при успехе."""
    backup_path = db_path.parent / f"{db_path.name}.pre-v2.bak"
    if not backup_path.exists():
        log.error("Backup-файл не найден: %s", backup_path)
        return 1
    log.info("Восстанавливаю БД из backup: %s → %s", backup_path, db_path)
    try:
        shutil.copy2(backup_path, db_path)
        log.info("Rollback выполнен успешно.")
        return 0
    except OSError as exc:
        log.error("Ошибка при восстановлении: %s", exc)
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Миграция БД devboard: добавить таблицу departments (ADR-003)."
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Путь к tasks.db (по умолчанию — из PRIDE_TASKS_DB или data/tasks.db)",
    )
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="Восстановить БД из .pre-v2.bak вместо миграции.",
    )
    args = parser.parse_args()

    db_path = args.db if args.db else _get_db_path()
    log.info("БД: %s", db_path)

    if args.rollback:
        sys.exit(rollback(db_path))
    else:
        sys.exit(migrate(db_path))


if __name__ == "__main__":
    main()

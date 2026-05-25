#!/usr/bin/env python3
"""Миграция B1 (1.7) — переименование роли 'тимлид' → 'dev-lead' в dev-отделе.

Использование:
    python scripts/migrate_тимлид_to_dev_lead.py              # запустить миграцию
    python scripts/migrate_тимлид_to_dev_lead.py --check      # только проверить статус

Идемпотентно: проверяет состояние перед UPDATE.
- Если роль 'dev-lead' уже существует в roles.dev → миграция не нужна (no-op).
- Если роль 'тимлид' в roles.dev существует → переименовывает в 'dev-lead'.
- Backup tasks.db.bak.<unix-timestamp> создаётся перед изменениями.
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
log = logging.getLogger("migrate_тимлид_to_dev_lead")


def _get_db_path() -> Path:
    env = os.environ.get("PRIDE_TASKS_DB")
    if env:
        return Path(env)
    return default_db_path()


def _make_backup(db_path: Path) -> Path:
    """Создаёт tasks.db.bak.<unix-ts>; возвращает путь к копии."""
    ts = int(time.time())
    backup_path = db_path.parent / f"{db_path.name}.bak.{ts}"
    shutil.copy2(db_path, backup_path)
    return backup_path


def _role_exists(conn: sqlite3.Connection, name: str, department_id: str | None = None) -> bool:
    """Проверяет существует ли роль с данным именем (опционально в отделе)."""
    if department_id is None:
        row = conn.execute(
            "SELECT name FROM roles WHERE name = ?", (name,)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT name FROM roles WHERE name = ? AND department_id = ?",
            (name, department_id),
        ).fetchone()
    return row is not None


def _get_role_info(conn: sqlite3.Connection, name: str) -> dict | None:
    """Получает полную информацию о роли."""
    row = conn.execute(
        "SELECT name, description, capabilities, department_id FROM roles WHERE name = ?",
        (name,),
    ).fetchone()
    if not row:
        return None
    return {
        "name": row[0],
        "description": row[1],
        "capabilities": row[2],
        "department_id": row[3],
    }


def migrate(db_path: Path) -> int:
    """Переименовывает тимлид → dev-lead в dev-отделе. Возвращает 0 при успехе."""
    if not db_path.exists():
        log.error("БД не найдена: %s", db_path)
        return 1

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = OFF")

        # Проверка: есть ли уже dev-lead в dev?
        if _role_exists(conn, "dev-lead", "dev"):
            log.info(
                "Роль 'dev-lead' в отделе 'dev' уже существует — миграция не нужна."
            )
            return 0

        # Проверка: есть ли тимлид в dev?
        if not _role_exists(conn, "тимлид", "dev"):
            log.warning(
                "Роль 'тимлид' не найдена в отделе 'dev'. "
                "Может быть, миграция уже была выполнена?"
            )
            return 0

        # Pre-flight backup перед изменениями.
        try:
            backup_path = _make_backup(db_path)
            log.info("Backup создан: %s", backup_path)
        except OSError as exc:
            log.error("Не удалось создать backup: %s", exc)
            return 1

        # Получить информацию о тимлиде перед изменением.
        timalead_info = _get_role_info(conn, "тимлид")
        if not timalead_info:
            log.error("Не удалось найти информацию о роли 'тимлид'")
            return 1

        log.info(
            "Переименовываю роль 'тимлид' → 'dev-lead' в отделе 'dev' ..."
        )
        conn.execute("BEGIN IMMEDIATE")

        # 1. Обновить tasks.assignee: тимлид → dev-lead
        conn.execute(
            "UPDATE tasks SET assignee = 'dev-lead' WHERE assignee = 'тимлид'"
        )
        tasks_updated = conn.total_changes
        log.info("  Обновлено %d строк в tasks (assignee = 'dev-lead')", tasks_updated)

        # 2. Удалить старую запись (тимлид) и вставить новую (dev-lead)
        conn.execute(
            "DELETE FROM roles WHERE name = 'тимлид' AND department_id = 'dev'"
        )
        conn.execute(
            "INSERT INTO roles (name, description, capabilities, department_id) "
            "VALUES (?, ?, ?, 'dev')",
            ("dev-lead", timalead_info["description"], timalead_info["capabilities"]),
        )
        log.info("  Роль переименована в таблице roles")

        conn.execute("COMMIT")
        log.info("Миграция B1 (1.7) завершена успешно.")
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
    """Проверяет статус миграции.
    Возвращает 0 если dev-lead уже есть (миграция выполнена),
    1 если тимлид есть (нужна миграция), 2 если ни того ни другого.
    """
    if not db_path.exists():
        log.error("БД не найдена: %s", db_path)
        return 1
    conn = sqlite3.connect(db_path)
    try:
        dev_lead_exists = _role_exists(conn, "dev-lead", "dev")
        тимлид_exists = _role_exists(conn, "тимлид", "dev")

        if dev_lead_exists:
            log.info(
                "✓ Роль 'dev-lead' в отделе 'dev' существует — миграция выполнена"
            )
            return 0
        elif тимлид_exists:
            log.info(
                "⚠ Роль 'тимлид' в отделе 'dev' существует — требуется миграция"
            )
            return 1
        else:
            log.info(
                "? Ни 'тимлид' ни 'dev-lead' в отделе 'dev' не найдены"
            )
            return 2
    finally:
        conn.close()


def count_dev_roles(db_path: Path) -> int:
    """Возвращает количество ролей в отделе 'dev'."""
    if not db_path.exists():
        return -1
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM roles WHERE department_id = 'dev'"
        ).fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def list_dev_roles(db_path: Path) -> list[str]:
    """Возвращает список всех ролей в отделе 'dev'."""
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM roles WHERE department_id = 'dev' ORDER BY name"
        ).fetchall()
        return [row[0] for row in rows]
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Миграция B1 (1.7): переименовать 'тимлид' → 'dev-lead' в отделе 'dev'."
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Путь к tasks.db (по умолчанию — из PRIDE_TASKS_DB или data/tasks.db)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Только проверить статус (без изменений).",
    )
    parser.add_argument(
        "--list-roles",
        action="store_true",
        help="Показать список ролей в отделе 'dev' и выход.",
    )
    args = parser.parse_args()

    db_path = args.db if args.db else _get_db_path()
    log.info("БД: %s", db_path)

    if args.list_roles:
        roles = list_dev_roles(db_path)
        count = len(roles)
        log.info("Ролей в отделе 'dev': %d", count)
        for role in roles:
            log.info("  - %s", role)
        sys.exit(0)

    if args.check:
        sys.exit(check(db_path))
    else:
        sys.exit(migrate(db_path))


if __name__ == "__main__":
    main()

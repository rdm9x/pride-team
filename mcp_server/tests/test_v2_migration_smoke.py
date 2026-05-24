"""S12.1 — Migration smoke v1.x → v2.0 (ADR-003, departments).

Цель: убедиться что upgrade с v1.6 (без таблицы departments / без колонок
department_id) на v2.0 не теряет данные и идемпотентен.

Используется fixture-снапшот `tests/fixtures/v1.6_snapshot.db` — sqlite-файл
со схемой v1.x и anonymized данными. Сборщик: `tests/fixtures/build_v1_6_snapshot.py`.

Сценарий теста:
  1. Скопировать fixture-snapshot в tmp_path.
  2. Зафиксировать «before» counts всех v1.x таблиц.
  3. Запустить `scripts/migrate_v2_departments.py` через subprocess
     (с PRIDE_TASKS_DB → tmp_path/tasks.db).
  4. Verify:
     - таблица departments создана, в ней есть запись 'dev';
     - schema_meta.version == 'v2.0-departments';
     - все tasks имеют department_id='dev';
     - все chat_messages имеют department_id='dev';
     - все НЕ-глобальные roles имеют department_id='dev';
     - HR/owner/user/пользователь остаются с department_id IS NULL (если присутствуют);
     - counts строк не изменились ни в одной из v1.x таблиц.
  5. Idempotency: запустить миграцию повторно — counts строк не растут,
     версия остаётся 'v2.0-departments'.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE_PATH = _REPO_ROOT / "tests" / "fixtures" / "v1.6_snapshot.db"
_MIGRATION_SCRIPT = _REPO_ROOT / "scripts" / "migrate_v2_departments.py"

# Глобальные роли — не получают department_id (см. _GLOBAL_ROLES в migrate_v2_departments).
_GLOBAL_ROLES = ("hr", "owner", "пользователь", "user")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _table_counts(conn: sqlite3.Connection, tables: list[str]) -> dict[str, int]:
    """Считает COUNT(*) для каждой таблицы. Если таблицы нет — возвращает 0."""
    res: dict[str, int] = {}
    for tbl in tables:
        try:
            res[tbl] = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        except sqlite3.OperationalError:
            res[tbl] = 0
    return res


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _run_migration(db_path: Path) -> subprocess.CompletedProcess[str]:
    """Запустить migrate_v2_departments.py в subprocess. Возвращает результат."""
    env = os.environ.copy()
    env["PRIDE_TASKS_DB"] = str(db_path)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(_MIGRATION_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def v1_db(tmp_path: Path) -> Path:
    """Копия v1.x snapshot в tmp_path. Возвращает путь к свежей копии."""
    if not _FIXTURE_PATH.exists():
        pytest.fail(
            f"v1.x fixture-snapshot не найден: {_FIXTURE_PATH}\n"
            "Запустите: python tests/fixtures/build_v1_6_snapshot.py"
        )
    dst = tmp_path / "tasks.db"
    shutil.copy2(_FIXTURE_PATH, dst)
    return dst


# ---------------------------------------------------------------------------
# Pre-condition tests — fixture действительно v1.x
# ---------------------------------------------------------------------------


def test_fixture_is_v1_schema(v1_db: Path) -> None:
    """Sanity: fixture-snapshot не содержит таблицы departments и колонок department_id."""
    conn = sqlite3.connect(v1_db)
    try:
        assert not _table_exists(conn, "departments"), \
            "Fixture не v1.x: уже есть таблица departments"
        assert not _table_exists(conn, "schema_meta"), \
            "Fixture не v1.x: уже есть таблица schema_meta"

        for tbl in ("tasks", "roles", "chat_messages"):
            cols = {row[1] for row in conn.execute(f"PRAGMA table_info({tbl})")}
            assert "department_id" not in cols, \
                f"Fixture не v1.x: в {tbl} уже есть department_id"

        # Должны быть какие-то данные (иначе нечего мигрировать).
        assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] > 0
        assert conn.execute("SELECT COUNT(*) FROM roles").fetchone()[0] > 0
        assert conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0] > 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Главный сценарий: миграция не теряет данные
# ---------------------------------------------------------------------------


def test_migration_v1_to_v2_no_data_loss(v1_db: Path) -> None:
    """Миграция v1.x → v2.0: counts всех v1-таблиц не меняются + backfill корректный."""
    v1_tables = [
        "tasks",
        "roles",
        "chat_messages",
        "task_comments",
        "task_dependencies",
        "claude_sessions",
    ]

    # === Before ===
    conn_before = sqlite3.connect(v1_db)
    try:
        before = _table_counts(conn_before, v1_tables)
        before_task_ids = {r[0] for r in conn_before.execute("SELECT id FROM tasks")}
        before_role_names = {r[0] for r in conn_before.execute("SELECT name FROM roles")}
        before_chat_ids = {r[0] for r in conn_before.execute("SELECT id FROM chat_messages")}
    finally:
        conn_before.close()

    # === Migrate ===
    result = _run_migration(v1_db)
    assert result.returncode == 0, (
        f"Миграция упала. stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    # === After ===
    conn_after = sqlite3.connect(v1_db)
    conn_after.row_factory = sqlite3.Row
    try:
        # 1. Counts всех v1-таблиц не изменились.
        after = _table_counts(conn_after, v1_tables)
        assert after == before, (
            f"Counts изменились после миграции.\nBefore: {before}\nAfter:  {after}"
        )

        # 2. Те же task_id / role_name / chat_id — никто не потерян, никто не задвоен.
        after_task_ids = {r[0] for r in conn_after.execute("SELECT id FROM tasks")}
        after_role_names = {r[0] for r in conn_after.execute("SELECT name FROM roles")}
        after_chat_ids = {r[0] for r in conn_after.execute("SELECT id FROM chat_messages")}
        assert after_task_ids == before_task_ids, "Изменился набор task_id"
        assert after_role_names == before_role_names, "Изменился набор role names"
        assert after_chat_ids == before_chat_ids, "Изменился набор chat ids"

        # 3. Таблица departments создана, в ней есть 'dev'.
        assert _table_exists(conn_after, "departments"), "Таблица departments не создана"
        dev = conn_after.execute(
            "SELECT id, name, archived_at FROM departments WHERE id='dev'"
        ).fetchone()
        assert dev is not None, "default department 'dev' не вставлен"
        assert dev["name"] == "Dev"
        assert dev["archived_at"] is None

        # 4. schema_meta.version == 'v2.0-departments'.
        assert _table_exists(conn_after, "schema_meta"), "schema_meta не создана"
        ver = conn_after.execute(
            "SELECT value FROM schema_meta WHERE key='version'"
        ).fetchone()
        assert ver is not None and ver["value"] == "v2.0-departments", (
            f"schema_meta.version != v2.0-departments (got: {ver and ver['value']})"
        )

        # 5. Все tasks → department_id='dev'.
        bad_tasks = conn_after.execute(
            "SELECT id, department_id FROM tasks WHERE department_id != 'dev' OR department_id IS NULL"
        ).fetchall()
        assert not bad_tasks, f"Tasks без department_id='dev': {[dict(r) for r in bad_tasks]}"

        # 6. Все chat_messages → department_id='dev'.
        bad_chats = conn_after.execute(
            "SELECT id, department_id FROM chat_messages "
            "WHERE department_id != 'dev' OR department_id IS NULL"
        ).fetchall()
        assert not bad_chats, f"Chat без department_id='dev': {[dict(r) for r in bad_chats]}"

        # 7. Roles: НЕ-глобальные → 'dev', глобальные (HR/owner/user/пользователь) → NULL.
        placeholders = ",".join("?" * len(_GLOBAL_ROLES))

        bad_non_global = conn_after.execute(
            f"SELECT name, department_id FROM roles "
            f"WHERE name NOT IN ({placeholders}) "
            f"  AND (department_id != 'dev' OR department_id IS NULL)",
            _GLOBAL_ROLES,
        ).fetchall()
        assert not bad_non_global, (
            f"Non-global roles без department_id='dev': {[dict(r) for r in bad_non_global]}"
        )

        # Глобальные роли, если они присутствуют, должны иметь NULL.
        bad_global = conn_after.execute(
            f"SELECT name, department_id FROM roles "
            f"WHERE name IN ({placeholders}) AND department_id IS NOT NULL",
            _GLOBAL_ROLES,
        ).fetchall()
        assert not bad_global, (
            f"Global roles НЕ должны иметь department_id, но имеют: {[dict(r) for r in bad_global]}"
        )
    finally:
        conn_after.close()


# ---------------------------------------------------------------------------
# Идемпотентность
# ---------------------------------------------------------------------------


def test_migration_is_idempotent(v1_db: Path) -> None:
    """Повторный запуск миграции не дублирует строки и оставляет schema_meta.version неизменной."""
    v1_tables = [
        "tasks",
        "roles",
        "chat_messages",
        "task_comments",
        "task_dependencies",
        "claude_sessions",
    ]
    v2_tables = v1_tables + ["departments", "schema_meta"]

    # Первый прогон.
    result1 = _run_migration(v1_db)
    assert result1.returncode == 0, (
        f"Первая миграция упала: {result1.stdout}\n{result1.stderr}"
    )

    conn = sqlite3.connect(v1_db)
    try:
        counts_after_1 = _table_counts(conn, v2_tables)
    finally:
        conn.close()

    # Второй прогон.
    result2 = _run_migration(v1_db)
    assert result2.returncode == 0, (
        f"Повторная миграция упала: {result2.stdout}\n{result2.stderr}"
    )
    # Скрипт должен сообщить «уже выполнена» (см. pre-flight).
    assert "Миграция уже выполнена" in (result2.stdout + result2.stderr), (
        "Повторный запуск не задетектил что миграция уже сделана.\n"
        f"stdout: {result2.stdout}\nstderr: {result2.stderr}"
    )

    conn = sqlite3.connect(v1_db)
    conn.row_factory = sqlite3.Row
    try:
        counts_after_2 = _table_counts(conn, v2_tables)
        assert counts_after_2 == counts_after_1, (
            f"Counts изменились между прогонами (дубли?).\n"
            f"After 1: {counts_after_1}\nAfter 2: {counts_after_2}"
        )

        # Версия осталась той же.
        ver = conn.execute(
            "SELECT value FROM schema_meta WHERE key='version'"
        ).fetchone()
        assert ver is not None and ver["value"] == "v2.0-departments"

        # Department 'dev' не задвоен (UNIQUE name + PRIMARY KEY id, но проверим явно).
        dev_count = conn.execute(
            "SELECT COUNT(*) FROM departments WHERE id='dev'"
        ).fetchone()[0]
        assert dev_count == 1, f"department 'dev' задвоен: count={dev_count}"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Третий прогон поверх идемпотентного состояния — стабильность.
# ---------------------------------------------------------------------------


def test_migration_third_run_stable(v1_db: Path) -> None:
    """Третий запуск (и любой последующий) ничего не меняет."""
    for _ in range(3):
        result = _run_migration(v1_db)
        assert result.returncode == 0

    conn = sqlite3.connect(v1_db)
    try:
        tasks_with_dev = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE department_id='dev'"
        ).fetchone()[0]
        tasks_total = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        assert tasks_with_dev == tasks_total > 0
    finally:
        conn.close()

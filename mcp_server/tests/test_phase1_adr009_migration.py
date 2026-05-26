"""B1 — миграция Phase-1 ADR-009 / ADR-007.

Покрытие:
  1. На свежей пустой БД миграция проходит, после — sqlite_master содержит
     5+ объектов, имя которых начинается на 'manager_' (table + fts +
     3 триггера + индексы).
  2. INSERT в `manager_chunks` → SELECT через `manager_fts` MATCH находит её
     (полнотекстовый поиск работает, триггер `_ai` синхронизирует данные).
  3. `planning_sessions` существует, индекс `idx_planning_phase` создан.
  4. Повторный запуск миграции (3 раза подряд) не падает — идемпотентность.
  5. Миграция на копии текущей tasks.db (если она есть в data/) не ломает
     существующие таблицы tasks / chat_messages / departments / roles.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION_SCRIPT = _REPO_ROOT / "scripts" / "migrate_phase1_adr009.py"
_LIVE_DB = _REPO_ROOT / "data" / "tasks.db"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_migration(db_path: Path, *extra_args: str) -> subprocess.CompletedProcess[str]:
    """Запустить migrate_phase1_adr009.py через subprocess, изолированно от живой БД."""
    env = os.environ.copy()
    env["DEVBOARD_TASKS_DB"] = str(db_path)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(_MIGRATION_SCRIPT), *extra_args],
        env=env,
        capture_output=True,
        text=True,
    )


def _fresh_empty_db(path: Path) -> None:
    """Создать минимальный sqlite-файл (пустой, без таблиц) по указанному пути."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.close()


def _list_manager_objects(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """Все sqlite_master объекты, относящиеся к manager-памяти.

    Сюда входят и manager_* (table/triggers/fts shadow), и idx_manager_*
    (partial-индексы по manager_chunks).
    """
    rows = conn.execute(
        "SELECT type, name FROM sqlite_master "
        "WHERE name LIKE 'manager\\_%' ESCAPE '\\' "
        "   OR name LIKE 'idx\\_manager\\_%' ESCAPE '\\' "
        "ORDER BY type, name"
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def _object_exists(conn: sqlite3.Connection, obj_type: str, name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type=? AND name=?",
            (obj_type, name),
        ).fetchone()
        is not None
    )


# ---------------------------------------------------------------------------
# Тест 1: миграция на свежей пустой БД создаёт все объекты
# ---------------------------------------------------------------------------


def test_fresh_empty_db_migrates_ok(tmp_path: Path) -> None:
    """Свежая БД → миграция → sqlite_master содержит ≥5 manager_* объектов."""
    db_path = tmp_path / "tasks.db"
    _fresh_empty_db(db_path)

    result = _run_migration(db_path)
    assert result.returncode == 0, (
        f"Миграция упала. stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    conn = sqlite3.connect(db_path)
    try:
        objs = _list_manager_objects(conn)
        # Ожидаем: manager_chunks (table), manager_fts + системные fts5-таблицы,
        # 3 триггера (manager_chunks_ai/ad/au), 2 индекса.
        # FTS5 создаёт shadow-таблицы manager_fts_data/idx/docsize/config — это
        # делает итоговое число >= 5 даже без shadow-учёта.
        names = {n for _, n in objs}

        # Базовые объекты из ADR-007:
        required = {
            "manager_chunks",
            "manager_fts",
            "manager_chunks_ai",
            "manager_chunks_ad",
            "manager_chunks_au",
            "idx_manager_chunks_user_source",
            "idx_manager_chunks_updated",
        }
        missing = required - names
        assert not missing, f"Не созданы объекты: {missing}\nЧто есть: {names}"

        # И минимум 5+ (table + fts + 3 trigger = 5 — без учёта индексов и shadow).
        assert len(objs) >= 5, f"sqlite_master.manager_*: {objs}"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Тест 2: FTS5 — INSERT в chunks → MATCH через manager_fts находит строку
# ---------------------------------------------------------------------------


def test_manager_fts_search_works(tmp_path: Path) -> None:
    """Триггер `_ai` синхронизирует insert в manager_chunks с manager_fts."""
    db_path = tmp_path / "tasks.db"
    _fresh_empty_db(db_path)

    result = _run_migration(db_path)
    assert result.returncode == 0, result.stderr

    now = int(time.time())
    conn = sqlite3.connect(db_path)
    try:
        # INSERT-ы трёх chunks с разным текстом.
        conn.execute(
            "INSERT INTO manager_chunks (user_id, source, text, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("owner", "note", "owner — директор владельца, наружная реклама.", now, now),
        )
        conn.execute(
            "INSERT INTO manager_chunks (user_id, source, text, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("owner", "recall", "Owner выбрал трёхуровневую иерархию (2026-05-25).", now, now),
        )
        conn.execute(
            "INSERT INTO manager_chunks (user_id, source, text, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("owner", "note", "Customer A, Customer B — ключевые клиенты.", now, now),
        )
        conn.commit()

        # FTS5 MATCH — должен найти точное слово.
        rows = conn.execute(
            "SELECT c.id, c.text FROM manager_fts f "
            "JOIN manager_chunks c ON c.id = f.rowid "
            "WHERE manager_fts MATCH ? ORDER BY rank",
            ("наружная",),
        ).fetchall()
        assert len(rows) == 1, f"FTS MATCH 'наружная' нашёл: {rows}"
        assert "наружная" in rows[0][1]

        # Ещё один поиск — другое слово.
        rows = conn.execute(
            "SELECT c.id FROM manager_fts f "
            "JOIN manager_chunks c ON c.id = f.rowid "
            "WHERE manager_fts MATCH ?",
            ("трёхуровневую",),
        ).fetchall()
        assert len(rows) == 1, "FTS MATCH 'трёхуровневую' не нашёл строку"

        # И поиск нескольких слов через AND.
        rows = conn.execute(
            "SELECT c.id FROM manager_fts f "
            "JOIN manager_chunks c ON c.id = f.rowid "
            "WHERE manager_fts MATCH ?",
            ("Customer A Customer B",),
        ).fetchall()
        assert len(rows) == 1, "FTS MATCH 'Customer A Customer B' не нашёл строку"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Тест 3: planning_sessions — таблица + индекс созданы
# ---------------------------------------------------------------------------


def test_planning_sessions_table_and_index(tmp_path: Path) -> None:
    db_path = tmp_path / "tasks.db"
    _fresh_empty_db(db_path)

    result = _run_migration(db_path)
    assert result.returncode == 0, result.stderr

    conn = sqlite3.connect(db_path)
    try:
        # Таблица существует.
        assert _object_exists(conn, "table", "planning_sessions")

        # Индекс существует.
        assert _object_exists(conn, "index", "idx_planning_phase")

        # Проверим что INSERT работает — структура корректная.
        now = int(time.time())
        conn.execute(
            "INSERT INTO planning_sessions ("
            "  id, owner_request, phase, departments_involved, started_at"
            ") VALUES (?, ?, ?, ?, ?)",
            ("ps-test-001", "Тестовый запрос owner-а", "gathering", '["dev"]', now),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id, phase, finished_at FROM planning_sessions WHERE id=?",
            ("ps-test-001",),
        ).fetchone()
        assert row is not None
        assert row[1] == "gathering"
        assert row[2] is None  # finished_at NULL → попадает в idx_planning_phase

        # И обращение к индексу через EXPLAIN QUERY PLAN (sanity-check).
        plan = conn.execute(
            "EXPLAIN QUERY PLAN SELECT id FROM planning_sessions "
            "WHERE phase='gathering' AND finished_at IS NULL"
        ).fetchall()
        plan_text = " ".join(str(r) for r in plan)
        assert "idx_planning_phase" in plan_text, (
            f"Запрос не использует idx_planning_phase: {plan_text}"
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Тест 4: идемпотентность — 3 прогона подряд
# ---------------------------------------------------------------------------


def test_migration_is_idempotent(tmp_path: Path) -> None:
    """Запуск 3 раза подряд не падает и не дублирует объекты."""
    db_path = tmp_path / "tasks.db"
    _fresh_empty_db(db_path)

    # Первый прогон.
    r1 = _run_migration(db_path)
    assert r1.returncode == 0, r1.stderr

    conn = sqlite3.connect(db_path)
    try:
        objs_after_1 = _list_manager_objects(conn)
    finally:
        conn.close()

    # Второй прогон — должен сработать no-op.
    r2 = _run_migration(db_path)
    assert r2.returncode == 0, r2.stderr
    assert "миграция не нужна" in (r2.stdout + r2.stderr).lower(), (
        f"Повторный запуск не задетектил уже выполненную миграцию.\n"
        f"stdout: {r2.stdout}\nstderr: {r2.stderr}"
    )

    # Третий прогон — тоже no-op.
    r3 = _run_migration(db_path)
    assert r3.returncode == 0, r3.stderr

    conn = sqlite3.connect(db_path)
    try:
        objs_after_3 = _list_manager_objects(conn)
        assert objs_after_3 == objs_after_1, (
            f"Список объектов изменился между прогонами.\n"
            f"After 1: {objs_after_1}\nAfter 3: {objs_after_3}"
        )

        # И --check возвращает 0.
        check = _run_migration(db_path, "--check")
        assert check.returncode == 0, check.stderr
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Тест 5: миграция на копии текущей tasks.db не ломает существующие таблицы
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _LIVE_DB.exists(), reason="data/tasks.db не существует")
def test_migration_on_live_db_copy_preserves_data(tmp_path: Path) -> None:
    """Копия живой tasks.db: counts старых таблиц неизменны, новые объекты появились."""
    db_copy = tmp_path / "tasks.db"
    shutil.copy2(_LIVE_DB, db_copy)

    # Список таблиц, которые точно должны существовать в live-БД и НЕ должны
    # меняться при миграции (некоторые могут быть пустыми — это ок).
    candidates = [
        "tasks",
        "chat_messages",
        "departments",
        "roles",
        "task_comments",
        "task_dependencies",
        "claude_sessions",
        "hr_sessions",
    ]

    conn_before = sqlite3.connect(db_copy)
    try:
        before: dict[str, int] = {}
        for tbl in candidates:
            row = conn_before.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (tbl,),
            ).fetchone()
            if row is None:
                continue  # таблицы нет — пропустить из проверки
            before[tbl] = conn_before.execute(
                f"SELECT COUNT(*) FROM {tbl}"
            ).fetchone()[0]
    finally:
        conn_before.close()

    assert before, "В live-БД не нашлось ни одной из ожидаемых таблиц — странно"

    # Was migration needed (объекты ещё не созданы) — мы должны увидеть backup.
    # Если live-БД уже содержит все объекты (например, init_db уже их создал) —
    # миграция корректно становится no-op и backup не создаётся. Покрываем оба
    # сценария.
    conn_check = sqlite3.connect(db_copy)
    try:
        already_migrated = (
            conn_check.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='manager_chunks'"
            ).fetchone()
            is not None
            and conn_check.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='planning_sessions'"
            ).fetchone()
            is not None
        )
    finally:
        conn_check.close()

    # Migrate.
    result = _run_migration(db_copy)
    assert result.returncode == 0, (
        f"Миграция упала. stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    backups = list(tmp_path.glob("tasks.db.bak.*"))
    if already_migrated:
        # No-op: backup не создаётся, в логе должно быть про idempotent.
        assert not backups, (
            f"No-op миграция не должна создавать backup, но создан: {backups}"
        )
    else:
        assert backups, f"Backup не создан рядом с {db_copy}"

    # After: counts старых таблиц неизменны + новые таблицы появились.
    conn_after = sqlite3.connect(db_copy)
    try:
        for tbl, cnt_before in before.items():
            cnt_after = conn_after.execute(
                f"SELECT COUNT(*) FROM {tbl}"
            ).fetchone()[0]
            assert cnt_after == cnt_before, (
                f"Таблица {tbl}: count изменился {cnt_before} → {cnt_after}"
            )

        # Новые таблицы есть.
        assert _object_exists(conn_after, "table", "planning_sessions")
        assert _object_exists(conn_after, "table", "manager_chunks")
        assert _object_exists(conn_after, "table", "manager_fts")
        assert _object_exists(conn_after, "trigger", "manager_chunks_ai")
        assert _object_exists(conn_after, "index", "idx_planning_phase")

        # FTS работает. Используем уникальный маркер чтобы не пересечься
        # с возможными seed-чанками core knowledge в live-db.
        marker = "ftsmarkerXyZqWv42"
        now = int(time.time())
        conn_after.execute(
            "INSERT INTO manager_chunks (user_id, source, text, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("owner", "note", f"test chunk {marker}", now, now),
        )
        conn_after.commit()
        rows = conn_after.execute(
            "SELECT c.id FROM manager_fts f "
            "JOIN manager_chunks c ON c.id = f.rowid "
            "WHERE manager_fts MATCH ?",
            (marker,),
        ).fetchall()
        assert len(rows) == 1
    finally:
        conn_after.close()


# ---------------------------------------------------------------------------
# Тест 6: init_db() (SCHEMA_SQL) создаёт те же объекты — fresh-install path
# ---------------------------------------------------------------------------


def test_init_db_creates_phase1_objects(tmp_path: Path) -> None:
    """ensure_schema() из db.py для свежей установки сразу даёт нужные объекты."""
    # init_db через прямой импорт — без subprocess.
    from devboard_tasks import db as pkg_db

    db_path = tmp_path / "tasks.db"
    pkg_db.init_db(db_path)

    conn = sqlite3.connect(db_path)
    try:
        required = [
            ("table",   "planning_sessions"),
            ("index",   "idx_planning_phase"),
            ("table",   "manager_chunks"),
            ("table",   "manager_fts"),
            ("trigger", "manager_chunks_ai"),
            ("trigger", "manager_chunks_ad"),
            ("trigger", "manager_chunks_au"),
            ("index",   "idx_manager_chunks_user_source"),
            ("index",   "idx_manager_chunks_updated"),
        ]
        for obj_type, name in required:
            assert _object_exists(conn, obj_type, name), (
                f"init_db() не создал {obj_type} {name}"
            )

        # FTS sync triggers работают и здесь.
        now = int(time.time())
        conn.execute(
            "INSERT INTO manager_chunks (user_id, source, text, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("owner", "note", "fresh install fts test", now, now),
        )
        conn.commit()
        rows = conn.execute(
            "SELECT rowid FROM manager_fts WHERE manager_fts MATCH ?",
            ("fresh",),
        ).fetchall()
        assert len(rows) == 1
    finally:
        conn.close()

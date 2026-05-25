"""B1 (1.7) — миграция 'тимлид' → 'dev-lead' в отделе dev.

Покрытие:
  1. На свежей БД без 'dev-lead' миграция переименовывает 'тимлид' в 'dev-lead'.
  2. Все tasks.assignee='тимлид' обновляются на 'dev-lead'.
  3. После миграции roles.dev содержит 7 ролей (dev-lead, бэкенд, qa, архитектор, frontend, devops, техписатель).
  4. Повторный запуск миграции — idempotent, не падает и ничего не меняет.
  5. На БД где уже есть dev-lead → миграция пропускается (no-op).
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION_SCRIPT = _REPO_ROOT / "scripts" / "migrate_тимлид_to_dev_lead.py"

# Ожидаемые роли в отделе dev (после миграции и инициализации)
_EXPECTED_DEV_ROLES = {
    "dev-lead",
    "бэкенд",
    "qa",
    "архитектор",
    "frontend",
    "devops",
    "техписатель",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_migration(db_path: Path, *extra_args: str) -> subprocess.CompletedProcess[str]:
    """Запустить migrate_тимлид_to_dev_lead.py через subprocess."""
    env = os.environ.copy()
    env["DEVBOARD_TASKS_DB"] = str(db_path)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(_MIGRATION_SCRIPT), *extra_args],
        env=env,
        capture_output=True,
        text=True,
    )


def _fresh_db_with_schema(path: Path) -> None:
    """Создаёт БД со схемой (таблицы, но без ролей — как v2.0.x)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        # Минимальная схема для тестов
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS departments (
              id            TEXT PRIMARY KEY,
              name          TEXT NOT NULL UNIQUE,
              description   TEXT NOT NULL DEFAULT '',
              template_id   TEXT,
              hr_session_id TEXT,
              icon          TEXT DEFAULT '🗂',
              created_at    INTEGER NOT NULL,
              archived_at   INTEGER
            );

            CREATE TABLE IF NOT EXISTS roles (
              name TEXT PRIMARY KEY,
              description TEXT NOT NULL,
              capabilities TEXT NOT NULL DEFAULT '[]',
              department_id TEXT REFERENCES departments(id)
            );

            CREATE TABLE IF NOT EXISTS tasks (
              id TEXT PRIMARY KEY,
              title TEXT NOT NULL,
              description TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'todo',
              assignee TEXT,
              reporter TEXT,
              priority TEXT NOT NULL DEFAULT 'P2',
              labels TEXT NOT NULL DEFAULT '[]',
              parent_id TEXT,
              requires_approval INTEGER NOT NULL DEFAULT 0,
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL,
              due_at INTEGER,
              completed_at INTEGER,
              result TEXT,
              department_id TEXT REFERENCES departments(id),
              requester_department_id TEXT REFERENCES departments(id),
              requester_role_slug TEXT,
              model_hint TEXT,
              FOREIGN KEY (parent_id) REFERENCES tasks(id)
            );

            CREATE TABLE IF NOT EXISTS task_comments (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              task_id TEXT NOT NULL,
              author TEXT NOT NULL,
              text TEXT NOT NULL,
              created_at INTEGER NOT NULL,
              FOREIGN KEY (task_id) REFERENCES tasks(id)
            );

            CREATE TABLE IF NOT EXISTS task_dependencies (
              task_id    TEXT NOT NULL,
              depends_on TEXT NOT NULL,
              created_at INTEGER NOT NULL,
              PRIMARY KEY (task_id, depends_on),
              FOREIGN KEY (task_id)    REFERENCES tasks(id),
              FOREIGN KEY (depends_on) REFERENCES tasks(id),
              CHECK (task_id != depends_on)
            );

            CREATE TABLE IF NOT EXISTS chat_messages (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              author TEXT NOT NULL,
              text TEXT NOT NULL,
              created_at INTEGER NOT NULL,
              department_id TEXT REFERENCES departments(id)
            );

            CREATE TABLE IF NOT EXISTS claude_sessions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              started_at INTEGER NOT NULL,
              finished_at INTEGER NOT NULL,
              duration_ms INTEGER,
              num_turns INTEGER,
              input_tokens INTEGER,
              output_tokens INTEGER,
              total_cost_usd REAL,
              model TEXT,
              is_error INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS hr_sessions (
              id                TEXT PRIMARY KEY,
              department_name   TEXT NOT NULL,
              state             TEXT NOT NULL,
              plan_json         TEXT,
              template_hint     TEXT,
              started_at        INTEGER,
              finished_at       INTEGER,
              iteration_count   INTEGER NOT NULL DEFAULT 0,
              last_message      TEXT,
              attempt_count     INTEGER NOT NULL DEFAULT 0
            );

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

            CREATE TABLE IF NOT EXISTS manager_chunks (
              id         INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id    TEXT NOT NULL,
              source     TEXT NOT NULL,
              text       TEXT NOT NULL,
              tags       TEXT NOT NULL DEFAULT '[]',
              updated_at INTEGER NOT NULL,
              archived_at INTEGER
            );
        """)
    finally:
        conn.close()


def _init_dev_department_and_roles(path: Path) -> None:
    """Инициализирует отдел 'dev' и стандартные роли (с 'тимлид')."""
    conn = sqlite3.connect(path)
    try:
        now = int(time.time())

        # Создать отдел dev
        conn.execute(
            "INSERT OR IGNORE INTO departments "
            "(id, name, description, icon, created_at) "
            "VALUES ('dev', 'Dev', 'Development team', '🛠', ?)",
            (now,),
        )

        # Вставить стандартные роли (включая 'тимлид')
        roles = [
            (
                "тимлид",
                "Координирует команду: читает канбан, декомпозирует задачи, делегирует через subagent'ов, ревьюит.",
                json.dumps(["декомпозиция", "делегирование", "ревью", "эскалация_пользователю"], ensure_ascii=False),
                "dev",
            ),
            (
                "бэкенд",
                "Python-разработчик. Flask/FastAPI, SQLite, MCP-сервера. Пишет код и юнит-тесты.",
                json.dumps(["python", "flask", "sqlite", "mcp", "pytest"], ensure_ascii=False),
                "dev",
            ),
            (
                "qa",
                "Тестировщик. Прогоняет тесты, ищет регресс, заводит баги бэкенду как подзадачи.",
                json.dumps(["pytest", "smoke", "coverage", "edge_cases", "регресс"], ensure_ascii=False),
                "dev",
            ),
            (
                "архитектор",
                "Проектирует абстракции (multi-LLM, plugin system), пишет ADR, ревьюит код по архитектуре.",
                json.dumps(["adr", "abstractions", "design_patterns", "code_review"], ensure_ascii=False),
                "dev",
            ),
            (
                "frontend",
                "HTML/CSS/JS, accessibility, i18n, onboarding-flow, marketplace UI. Без фреймворков.",
                json.dumps(["vanilla_js", "css", "a11y", "i18n", "design_system"], ensure_ascii=False),
                "dev",
            ),
            (
                "devops",
                "Docker, GitHub Actions, deployment, security hardening, backup strategies.",
                json.dumps(["docker", "github_actions", "systemd", "security", "monitoring"], ensure_ascii=False),
                "dev",
            ),
            (
                "техписатель",
                "English docs, README, CONTRIBUTING, ARCHITECTURE, видео-демо сценарии.",
                json.dumps(["english", "markdown", "mermaid", "screenshots", "demo_scripts"], ensure_ascii=False),
                "dev",
            ),
        ]

        for name, desc, caps, dept_id in roles:
            conn.execute(
                "INSERT OR IGNORE INTO roles (name, description, capabilities, department_id) "
                "VALUES (?, ?, ?, ?)",
                (name, desc, caps, dept_id),
            )

        conn.commit()
    finally:
        conn.close()


def _create_test_task(path: Path, task_id: str, assignee: str) -> None:
    """Создаёт тестовую задачу с указанным assignee."""
    conn = sqlite3.connect(path)
    try:
        now = int(time.time())
        conn.execute(
            "INSERT INTO tasks "
            "(id, title, description, status, assignee, priority, created_at, updated_at, department_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (task_id, "Test Task", "", "todo", assignee, "P2", now, now, "dev"),
        )
        conn.commit()
    finally:
        conn.close()


def _get_role_names_in_dev(path: Path) -> set[str]:
    """Возвращает все имена ролей в отделе 'dev'."""
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute(
            "SELECT name FROM roles WHERE department_id = 'dev' ORDER BY name"
        ).fetchall()
        return {row[0] for row in rows}
    finally:
        conn.close()


def _get_tasks_assignee(path: Path, assignee: str) -> list[str]:
    """Возвращает все id задач с указанным assignee."""
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute(
            "SELECT id FROM tasks WHERE assignee = ? ORDER BY id",
            (assignee,),
        ).fetchall()
        return [row[0] for row in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


def test_migration_on_fresh_db_with_тимлид():
    """1. На свежей БД с 'тимлид' миграция переименовывает в 'dev-lead'."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        # Создать БД со схемой и ролями (включая тимлид)
        _fresh_db_with_schema(db_path)
        _init_dev_department_and_roles(db_path)

        # Проверить до миграции
        roles_before = _get_role_names_in_dev(db_path)
        assert "тимлид" in roles_before
        assert "dev-lead" not in roles_before

        # Запустить миграцию
        result = _run_migration(db_path)
        assert result.returncode == 0, f"stderr: {result.stderr}"

        # Проверить после миграции
        roles_after = _get_role_names_in_dev(db_path)
        assert "тимлид" not in roles_after
        assert "dev-lead" in roles_after
        assert roles_after == _EXPECTED_DEV_ROLES


def test_migration_updates_task_assignee():
    """2. Все задачи с assignee='тимлид' обновляются на 'dev-lead'."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        _fresh_db_with_schema(db_path)
        _init_dev_department_and_roles(db_path)

        # Создать несколько задач с assignee=тимлид
        _create_test_task(db_path, "task-1", "тимлид")
        _create_test_task(db_path, "task-2", "тимлид")
        _create_test_task(db_path, "task-3", "бэкенд")  # другой assignee

        # Проверить до миграции
        тимлид_tasks_before = _get_tasks_assignee(db_path, "тимлид")
        assert len(тимлид_tasks_before) == 2

        # Запустить миграцию
        result = _run_migration(db_path)
        assert result.returncode == 0

        # Проверить после миграции
        тимлид_tasks_after = _get_tasks_assignee(db_path, "тимлид")
        dev_lead_tasks_after = _get_tasks_assignee(db_path, "dev-lead")

        assert len(тимлид_tasks_after) == 0
        assert set(dev_lead_tasks_after) == {"task-1", "task-2"}


def test_migration_idempotent_no_op():
    """3. Повторный запуск миграции — idempotent, не меняет ничего."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        _fresh_db_with_schema(db_path)
        _init_dev_department_and_roles(db_path)

        # Запустить миграцию первый раз
        result1 = _run_migration(db_path)
        assert result1.returncode == 0

        roles_after_first = _get_role_names_in_dev(db_path)

        # Запустить миграцию второй раз
        result2 = _run_migration(db_path)
        assert result2.returncode == 0

        roles_after_second = _get_role_names_in_dev(db_path)

        # Должны быть идентичны
        assert roles_after_first == roles_after_second


def test_migration_when_dev_lead_already_exists():
    """4. Если dev-lead уже есть, миграция пропускается (no-op, exit 0)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        _fresh_db_with_schema(db_path)
        _init_dev_department_and_roles(db_path)

        # Вручную переименовать в dev-lead и удалить тимлид
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("DELETE FROM roles WHERE name = 'тимлид'")
            conn.execute(
                "INSERT INTO roles (name, description, capabilities, department_id) "
                "VALUES ('dev-lead', 'Team lead', '[]', 'dev')"
            )
            conn.commit()
        finally:
            conn.close()

        # Запустить миграцию (должна быть no-op)
        result = _run_migration(db_path)
        assert result.returncode == 0

        # Проверить что dev-lead остался
        roles = _get_role_names_in_dev(db_path)
        assert "dev-lead" in roles


def test_migration_check_flag():
    """5. Флаг --check показывает статус без изменений."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        _fresh_db_with_schema(db_path)
        _init_dev_department_and_roles(db_path)

        # Запустить --check (до миграции)
        result = _run_migration(db_path, "--check")
        # Должен вернуть 1 (требуется миграция)
        assert result.returncode == 1

        # Запустить настоящую миграцию
        result = _run_migration(db_path)
        assert result.returncode == 0

        # Запустить --check (после миграции)
        result = _run_migration(db_path, "--check")
        # Должен вернуть 0 (миграция выполнена)
        assert result.returncode == 0


def test_migration_list_roles_flag():
    """6. Флаг --list-roles показывает роли в dev."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        _fresh_db_with_schema(db_path)
        _init_dev_department_and_roles(db_path)

        # Запустить миграцию сначала
        result = _run_migration(db_path)
        assert result.returncode == 0

        # Запустить --list-roles
        result = _run_migration(db_path, "--list-roles")
        assert result.returncode == 0

        # Проверить что в stdout есть 7 ролей
        output = result.stderr + result.stdout  # логирование может идти в stderr
        for role in _EXPECTED_DEV_ROLES:
            assert role in output, f"Role '{role}' not found in output"


def test_expected_seven_dev_roles():
    """7. После миграции в roles.dev ровно 7 ролей."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        _fresh_db_with_schema(db_path)
        _init_dev_department_and_roles(db_path)

        result = _run_migration(db_path)
        assert result.returncode == 0

        roles = _get_role_names_in_dev(db_path)
        assert len(roles) == 7
        assert roles == _EXPECTED_DEV_ROLES

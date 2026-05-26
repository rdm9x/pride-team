"""SQLite-слой канбана devboard-tasks.

Один файл БД (по умолчанию devboard/data/tasks.db).
Соединения создаются на каждый вызов — для thread-safety. Write-операции
сериализуются через `BEGIN IMMEDIATE` (SQLite reserved lock) + fcntl
эксклюзивный lock на отдельный файл `tasks.db.lock` — повторяет паттерн
client_card._atomic_modify для гарантии «никаких lost-update» при
параллельных claim_task / submit_result / update_task.

Схема — см. AGENTS.md §mcp_server.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

# Кросс-платформенный файл-lock: fcntl на Unix, msvcrt на Windows.
if sys.platform == "win32":  # pragma: no cover -- ветка тестируется отдельно на Win
    import msvcrt

    def _acquire_lock(fd: int) -> None:
        # Блокирующий exclusive-lock одного байта файла. msvcrt не поддерживает
        # offset=0 для LK_LOCK на нулевой длине файла, поэтому пишем 1 байт.
        os.lseek(fd, 0, os.SEEK_SET)
        # Если файл пустой — допишем байт-маркер.
        try:
            stat = os.fstat(fd)
            if stat.st_size == 0:
                os.write(fd, b"\0")
                os.lseek(fd, 0, os.SEEK_SET)
        except OSError:
            pass
        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)

    def _release_lock(fd: int) -> None:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass

else:
    import fcntl

    def _acquire_lock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX)

    def _release_lock(fd: int) -> None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass

# === Конфигурация ===

_DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "tasks.db"


def default_db_path() -> Path:
    """Путь к БД канбана. DEVBOARD_TASKS_DB переопределяет (для тестов)."""

    env = os.environ.get("DEVBOARD_TASKS_DB")
    if env:
        return Path(env)
    return _DEFAULT_DB_PATH


# === Схема ===

SCHEMA_SQL = """
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

CREATE TABLE IF NOT EXISTS projects (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  code        TEXT UNIQUE NOT NULL,        -- 'PRJ-001'
  slug        TEXT UNIQUE NOT NULL,        -- 'landing-outdoor' (latin)
  title       TEXT NOT NULL,                -- 'Лендинг outdoor billboards'
  status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','completed','archived')),
  created_at  INTEGER NOT NULL,
  archived_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);

CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'todo',
  assignee TEXT,
  reporter TEXT,
  priority TEXT NOT NULL DEFAULT 'P2',
  labels TEXT NOT NULL DEFAULT '[]',          -- JSON array
  parent_id TEXT,
  requires_approval INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  due_at INTEGER,
  completed_at INTEGER,
  result TEXT,                                 -- JSON object | NULL
  department_id TEXT REFERENCES departments(id),
  requester_department_id TEXT REFERENCES departments(id),  -- S11.1: ADR-005, NULL для intra
  requester_role_slug TEXT,                                  -- S11.1: ADR-005, slug Lead-заказчика
  model_hint TEXT,                                           -- S15.2: ADR-006, hint для роутера (opus/sonnet/haiku)
  enabled INTEGER NOT NULL DEFAULT 1,                        -- F2.1: чекбокс на todo-карточке (1=активна, 0=пропустить)
  project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,  -- группировка в проекты (PRJ-NNN)
  FOREIGN KEY (parent_id) REFERENCES tasks(id)
);

CREATE INDEX IF NOT EXISTS idx_tasks_status   ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_assignee ON tasks(assignee);
CREATE INDEX IF NOT EXISTS idx_tasks_parent   ON tasks(parent_id);
-- idx_tasks_project_id создаётся в _ensure_tasks_project_id_column,
-- чтобы не падать на старых БД, где tasks ещё без колонки project_id.

CREATE TABLE IF NOT EXISTS task_comments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT NOT NULL,
  author TEXT NOT NULL,
  text TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  FOREIGN KEY (task_id) REFERENCES tasks(id)
);

CREATE INDEX IF NOT EXISTS idx_comments_task ON task_comments(task_id);

CREATE TABLE IF NOT EXISTS task_artifacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT NOT NULL,
  file_path TEXT NOT NULL,
  kind TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  FOREIGN KEY (task_id) REFERENCES tasks(id),
  CONSTRAINT unique_artifact UNIQUE (task_id, file_path)
);

CREATE INDEX IF NOT EXISTS idx_artifacts_task ON task_artifacts(task_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_created ON task_artifacts(created_at);

CREATE TABLE IF NOT EXISTS roles (
  name TEXT PRIMARY KEY,
  description TEXT NOT NULL,
  capabilities TEXT NOT NULL DEFAULT '[]',     -- JSON array
  department_id TEXT REFERENCES departments(id)
);

CREATE TABLE IF NOT EXISTS task_dependencies (
  task_id    TEXT NOT NULL,         -- задача, которая ждёт
  depends_on TEXT NOT NULL,         -- задача, которая её блокирует
  created_at INTEGER NOT NULL,
  PRIMARY KEY (task_id, depends_on),
  FOREIGN KEY (task_id)    REFERENCES tasks(id),
  FOREIGN KEY (depends_on) REFERENCES tasks(id),
  CHECK (task_id != depends_on)
);

CREATE INDEX IF NOT EXISTS idx_deps_task    ON task_dependencies(task_id);
CREATE INDEX IF NOT EXISTS idx_deps_blocker ON task_dependencies(depends_on);

-- Phase 3a (B1, ADR-011 §2.3): Threads для чата Owner ↔ Управляющий.
-- Типы: 'direct' (повседневные) и 'planning' (планёрка с обсуждением лидов).
-- Создаём перед chat_messages, т.к. messages ссылаются на threads.
CREATE TABLE IF NOT EXISTS chat_threads (
  id                      TEXT PRIMARY KEY,
  title                   TEXT NOT NULL,
  kind                    TEXT NOT NULL DEFAULT 'direct' CHECK (kind IN ('direct','planning')),
  participants            TEXT NOT NULL DEFAULT '[]',     -- JSON: [{role_slug, joined_at}]
  status                  TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','finished','archived','aborted')),
  created_at              INTEGER NOT NULL,
  updated_at              INTEGER NOT NULL,
  finished_at             INTEGER,
  -- planning-specific (NULL для direct):
  source_problem          TEXT,                            -- что owner написал в начале
  decision_summary        TEXT,                            -- итоговый отчёт Управляющего
  decision_approved_at    INTEGER,                         -- когда owner апрувнул
  decision_created_tasks  TEXT                             -- JSON: [{task_id, dept_id}]
);

CREATE INDEX IF NOT EXISTS idx_chat_thread_created
  ON chat_threads(created_at);

CREATE INDEX IF NOT EXISTS idx_chat_thread_status
  ON chat_threads(status) WHERE finished_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_chat_threads_updated
  ON chat_threads(updated_at DESC);

CREATE TABLE IF NOT EXISTS chat_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  author TEXT NOT NULL,            -- 'пользователь' | 'тимлид' | 'бэкенд' | 'qa' | 'system'
  text TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  department_id TEXT REFERENCES departments(id),
  thread_id TEXT REFERENCES chat_threads(id)    -- B1 миграция: привязка к threads
);

CREATE INDEX IF NOT EXISTS idx_chat_created ON chat_messages(created_at);
CREATE INDEX IF NOT EXISTS idx_chat_messages_thread ON chat_messages(thread_id);

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

CREATE INDEX IF NOT EXISTS idx_sessions_finished ON claude_sessions(finished_at);

-- S10.3 (ADR-004): HR pipeline state machine.
-- Состояния (column `state`):
--   hr_planning | awaiting_owner_review | hr_revising | hr_activating
--   active | aborted
-- Подробное описание — ADR-004 §2.2.
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

CREATE INDEX IF NOT EXISTS idx_hr_sessions_state ON hr_sessions(state);

-- B1 (ADR-009 §2.4): планёрки руководителей отделов.
-- Хранят состояние «совещаний» инициированных Управляющим: фазы, лог обсуждения,
-- консолидированное предложение, вопросы к owner-у, созданные cross-task'и.
CREATE TABLE IF NOT EXISTS planning_sessions (
  id                    TEXT PRIMARY KEY,
  owner_request         TEXT NOT NULL,
  phase                 TEXT NOT NULL,           -- 'gathering' | 'discussion' | 'consolidation' | 'distribution' | 'done'
  departments_involved  TEXT NOT NULL,           -- JSON array of dept ids
  discussion_log        TEXT,                    -- JSON: [{author, role, text, timestamp}, ...]
  consolidated_proposal TEXT,
  questions_for_owner   TEXT,
  owner_answer          TEXT,
  created_tasks         TEXT,                    -- JSON: [{dept, task_id}, ...]
  started_at            INTEGER NOT NULL,
  finished_at           INTEGER,
  -- Phase 3b: оркестрация и лимиты.
  thread_id             TEXT REFERENCES chat_threads(id),
  topic                 TEXT,
  total_rounds          INTEGER NOT NULL DEFAULT 3,
  current_round         INTEGER NOT NULL DEFAULT 0,
  status                TEXT NOT NULL DEFAULT 'pending',  -- pending|running|aborted|done
  cost_limit_usd        REAL NOT NULL DEFAULT 2.0,
  cost_so_far_usd       REAL NOT NULL DEFAULT 0,
  -- Owner-decision на финальном отчёте Управляющего.
  decision              TEXT,                    -- 'accept'|'reject'|'revise'|NULL
  decided_at            INTEGER,
  decision_comment      TEXT,
  -- Профиль моделей для subprocess'ов планёрки (lead/synthesis/dispatch/revise).
  -- 'base' = sonnet везде; 'deep' = opus на synthesis/revise.
  model_profile         TEXT NOT NULL DEFAULT 'base'
);

-- Активные планёрки — самый частый запрос Управляющего при старте сессии.
CREATE INDEX IF NOT EXISTS idx_planning_phase
  ON planning_sessions(phase) WHERE finished_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_planning_status
  ON planning_sessions(status) WHERE status != 'done';

-- B1 (ADR-007 §2.1): долгосрочная память Управляющего — chunks + FTS5.
-- Хранит structured-факты, recall-выводы, итоги планёрок. Доступ только у роли
-- managing-director через MCP-tools manager_memory_*.
CREATE TABLE IF NOT EXISTS manager_chunks (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id      TEXT NOT NULL DEFAULT 'owner',
  source       TEXT NOT NULL,                  -- 'conversation' | 'note' | 'recall' | 'planning' | 'import'
  path         TEXT,                           -- chat#1234, adr/0009, planning_session#abc, ...
  start_line   INTEGER,
  end_line     INTEGER,
  text         TEXT NOT NULL,
  embedding    BLOB,                           -- nullable: vector search в Фазе 2
  tags         TEXT NOT NULL DEFAULT '[]',     -- JSON array
  created_at   INTEGER NOT NULL,
  updated_at   INTEGER NOT NULL,
  archived_at  INTEGER                         -- soft-delete
);

-- Полнотекстовый поиск (FTS5) по тексту чанков.
CREATE VIRTUAL TABLE IF NOT EXISTS manager_fts USING fts5(
  text,
  content='manager_chunks',
  content_rowid='id',
  tokenize='unicode61 remove_diacritics 1'
);

-- Синхронизация FTS-индекса с основной таблицей.
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

-- S17.5 (Task 99119C362B4A): Состояние приложения дашборда (для персистирования)
-- Сохраняет config-опции которые не должны теряться при перезагрузке процесса
CREATE TABLE IF NOT EXISTS app_state (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at INTEGER NOT NULL
);
"""

# Базовый набор ролей. Загружается при init_db, если ролей в таблице ещё нет.
_DEFAULT_ROLES: tuple[tuple[str, str, list[str]], ...] = (
    (
        "тимлид",
        "Координирует команду: читает канбан, декомпозирует задачи, делегирует через subagent'ов, ревьюит.",
        ["декомпозиция", "делегирование", "ревью", "эскалация_пользователю"],
    ),
    (
        "бэкенд",
        "Python-разработчик. Flask/FastAPI, SQLite, MCP-сервера. Пишет код и юнит-тесты.",
        ["python", "flask", "sqlite", "mcp", "pytest"],
    ),
    (
        "qa",
        "Тестировщик. Прогоняет тесты, ищет регресс, заводит баги бэкенду как подзадачи.",
        ["pytest", "smoke", "coverage", "edge_cases", "регресс"],
    ),
    (
        "архитектор",
        "Проектирует абстракции (multi-LLM, plugin system), пишет ADR, ревьюит код по архитектуре.",
        ["adr", "abstractions", "design_patterns", "code_review"],
    ),
    (
        "frontend",
        "HTML/CSS/JS, accessibility, i18n, onboarding-flow, marketplace UI. Без фреймворков.",
        ["vanilla_js", "css", "a11y", "i18n", "design_system"],
    ),
    (
        "devops",
        "Docker, GitHub Actions, deployment, security hardening, backup strategies.",
        ["docker", "github_actions", "systemd", "security", "monitoring"],
    ),
    (
        "техписатель",
        "English docs, README, CONTRIBUTING, ARCHITECTURE, видео-демо сценарии.",
        ["english", "markdown", "mermaid", "screenshots", "demo_scripts"],
    ),
)


# === fcntl-lock ===


def _lock_path(db_path: Path) -> Path:
    return db_path.parent / f"{db_path.name}.lock"


@contextmanager
def write_lock(db_path: Path) -> Iterator[None]:
    """Эксклюзивный fcntl-lock на запись.

    Сериализует параллельных writer'ов даже когда они используют разные
    sqlite3-connection'ы. Закрывает класс lost-update race: «два потока
    прочли одинаковую старую версию строки, оба записали, последний
    выиграл». Аналогично client_card._atomic_modify (см. там docstring).

    Lock-файл создаётся при первом обращении и далее не удаляется —
    fcntl-блокировка живёт на FD, а не на inode.
    """

    db_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = _lock_path(db_path)
    # 'a+b' — binary-режим нужен для msvcrt.locking; на Unix тоже работает.
    with open(lock_file, "a+b") as f:
        _acquire_lock(f.fileno())
        try:
            yield
        finally:
            _release_lock(f.fileno())


# === Подключение и init ===


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        db_path,
        timeout=10.0,
        isolation_level=None,  # ручные транзакции через BEGIN
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    # WAL — лучше для параллельных читателей.
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, col_def: str) -> None:
    """Добавляет колонку в таблицу если её ещё нет (обход отсутствия ADD COLUMN IF NOT EXISTS в SQLite)."""
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")


def ensure_dev_department(conn: sqlite3.Connection) -> None:
    """Создаёт default-отдел 'dev' и мигрирует существующие данные в него.

    Идемпотентно: безопасно вызывать несколько раз.
    - Вставляет запись 'dev' в departments если её нет.
    - Добавляет department_id в tasks/roles/chat_messages если колонок ещё нет.
    - Backfill: все tasks → 'dev', все chat_messages → 'dev'.
    - roles: все НЕ-глобальные роли → 'dev'; HR/owner/пользователь/user → NULL (глобальные).
    """
    now = int(time.time())

    # Убедиться что колонки есть (для БД созданных до этой миграции).
    _add_column_if_missing(conn, "tasks", "department_id", "TEXT REFERENCES departments(id)")
    _add_column_if_missing(conn, "roles", "department_id", "TEXT REFERENCES departments(id)")
    _add_column_if_missing(conn, "chat_messages", "department_id", "TEXT REFERENCES departments(id)")

    # S11.1 (ADR-005): inter-department колонки. Idempotent — добавляем только если ещё нет.
    _add_column_if_missing(conn, "tasks", "requester_department_id", "TEXT REFERENCES departments(id)")
    _add_column_if_missing(conn, "tasks", "requester_role_slug", "TEXT")

    # S15.2 (ADR-006): per-task model hint. Idempotent.
    _add_column_if_missing(conn, "tasks", "model_hint", "TEXT")

    # F2.1: чекбокс enabled (1=активна, 0=пропустить при старте сессии). Idempotent.
    _add_column_if_missing(conn, "tasks", "enabled", "INTEGER NOT NULL DEFAULT 1")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_tasks_requester_dept "
        "ON tasks(requester_department_id) WHERE requester_department_id IS NOT NULL"
    )

    # Создать индексы если нет.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_department  ON tasks(department_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_dept_status ON tasks(department_id, status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_department   ON chat_messages(department_id)")

    # Вставить default department 'dev' если нет.
    conn.execute(
        "INSERT OR IGNORE INTO departments (id, name, description, template_id, hr_session_id, icon, created_at) "
        "VALUES ('dev', 'Dev', 'Команда разработки devboard (мигрировано с v1.x)', NULL, NULL, '🛠', ?)",
        (now,),
    )

    # Backfill tasks.
    conn.execute("UPDATE tasks SET department_id = 'dev' WHERE department_id IS NULL")

    # Backfill chat_messages.
    conn.execute("UPDATE chat_messages SET department_id = 'dev' WHERE department_id IS NULL")

    # Backfill roles — кроме глобальных.
    _GLOBAL_ROLES = ("hr", "owner", "пользователь", "user")
    placeholders = ",".join("?" * len(_GLOBAL_ROLES))
    conn.execute(
        f"UPDATE roles SET department_id = 'dev' "
        f"WHERE department_id IS NULL AND name NOT IN ({placeholders})",
        _GLOBAL_ROLES,
    )


def _ensure_hr_sessions_columns(conn: sqlite3.Connection) -> None:
    """Idempotent миграция колонок таблицы hr_sessions (S10.3, ADR-004).

    На случай если БД создавалась до S10.3 и таблица была пуста / без
    некоторых полей. SQLite не поддерживает ADD COLUMN IF NOT EXISTS, поэтому
    делаем через PRAGMA + try/except. Безопасно вызывать многократно.
    """
    try:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(hr_sessions)")}
        if not existing:
            return  # таблицы вообще нет — её создаст SCHEMA_SQL выше
        _expected = {
            "plan_json":       "TEXT",
            "template_hint":   "TEXT",
            "started_at":      "INTEGER",
            "finished_at":     "INTEGER",
            "iteration_count": "INTEGER NOT NULL DEFAULT 0",
            "last_message":    "TEXT",
            "attempt_count":   "INTEGER NOT NULL DEFAULT 0",
        }
        for col, col_def in _expected.items():
            if col not in existing:
                try:
                    conn.execute(f"ALTER TABLE hr_sessions ADD COLUMN {col} {col_def}")
                except sqlite3.OperationalError:
                    # Колонка уже добавлена в параллельном вызове или диалект SQLite
                    # не позволил NOT NULL DEFAULT — игнорируем, главное не упасть.
                    pass
    except sqlite3.OperationalError:
        # Таблица не существует — будет создана в SCHEMA_SQL.
        pass


def _ensure_planning_sessions_columns(conn: sqlite3.Connection) -> None:
    """Миграция: добавить Phase 3b колонки в planning_sessions для старых БД."""
    try:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(planning_sessions)")}
        if not existing:
            return  # таблицы нет — её создаст SCHEMA_SQL
        expected = {
            "thread_id":        "TEXT",
            "topic":            "TEXT",
            "total_rounds":     "INTEGER NOT NULL DEFAULT 3",
            "current_round":    "INTEGER NOT NULL DEFAULT 0",
            "status":           "TEXT NOT NULL DEFAULT 'pending'",
            "cost_limit_usd":   "REAL NOT NULL DEFAULT 2.0",
            "cost_so_far_usd":  "REAL NOT NULL DEFAULT 0",
            "decision":         "TEXT",
            "decided_at":       "INTEGER",
            "decision_comment": "TEXT",
            "model_profile":    "TEXT NOT NULL DEFAULT 'base'",
        }
        for col, col_def in expected.items():
            if col not in existing:
                try:
                    conn.execute(f"ALTER TABLE planning_sessions ADD COLUMN {col} {col_def}")
                except sqlite3.OperationalError:
                    pass
        try:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_planning_status "
                "ON planning_sessions(status) WHERE status != 'done'"
            )
        except sqlite3.OperationalError:
            pass
    except sqlite3.OperationalError:
        pass


def _ensure_tasks_project_id_column(conn: sqlite3.Connection) -> None:
    """Миграция: добавить tasks.project_id для старых БД без этой колонки.

    Новые БД получают колонку сразу через SCHEMA_SQL. Для существующих БД,
    созданных до появления projects, эта функция добавляет колонку. Индекс
    создаётся всегда (после возможного ALTER), чтобы покрыть оба случая.
    """
    try:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
        if "project_id" not in existing:
            try:
                conn.execute(
                    "ALTER TABLE tasks ADD COLUMN project_id INTEGER "
                    "REFERENCES projects(id) ON DELETE SET NULL"
                )
            except sqlite3.OperationalError:
                pass  # параллельное добавление — игнорируем
        try:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_project_id ON tasks(project_id)"
            )
        except sqlite3.OperationalError:
            pass  # колонки всё ещё нет (старая БД и ALTER упал) — пропускаем
    except sqlite3.OperationalError:
        pass  # таблицы tasks нет (вряд ли)


def _migrate_тимлид_to_dev_lead(conn: sqlite3.Connection) -> None:
    """B1 (1.7) миграция: переименование роли 'тимлид' → 'dev-lead' в dev-отделе.

    Идемпотентная миграция. Если 'dev-lead' уже существует, то ничего не делается.
    Если 'тимлид' существует, переименовывается в 'dev-lead' вместе с обновлением
    assignee в tasks.
    """
    try:
        # Проверка: есть ли уже dev-lead в dev?
        row = conn.execute(
            "SELECT name FROM roles WHERE name = 'dev-lead' AND department_id = 'dev'"
        ).fetchone()
        if row:
            # Миграция уже выполнена
            return

        # Проверка: есть ли тимлид в dev?
        row = conn.execute(
            "SELECT name, description, capabilities FROM roles "
            "WHERE name = 'тимлид' AND department_id = 'dev'"
        ).fetchone()
        if not row:
            # Ничего не делаем — ни того ни другого нет
            return

        # Извлечь информацию о тимлиде
        тимлид_desc = row[1]
        тимлид_caps = row[2]

        # Обновить tasks.assignee: тимлид → dev-lead
        conn.execute(
            "UPDATE tasks SET assignee = 'dev-lead' WHERE assignee = 'тимлид'"
        )

        # Удалить старую запись и вставить новую
        conn.execute(
            "DELETE FROM roles WHERE name = 'тимлид' AND department_id = 'dev'"
        )
        conn.execute(
            "INSERT INTO roles (name, description, capabilities, department_id) "
            "VALUES ('dev-lead', ?, ?, 'dev')",
            (тимлид_desc, тимлид_caps),
        )
    except sqlite3.OperationalError:
        # Таблица roles может не существовать (вряд ли, но на случай)
        pass


def init_db(db_path: Optional[Path] = None) -> Path:
    """Создаёт схему и базовые роли. Идемпотентно."""

    path = Path(db_path) if db_path else default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with write_lock(path):
        conn = _connect(path)
        try:
            conn.executescript(SCHEMA_SQL)
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute("SELECT COUNT(*) AS n FROM roles")
            if cur.fetchone()["n"] == 0:
                for name, desc, caps in _DEFAULT_ROLES:
                    conn.execute(
                        "INSERT INTO roles (name, description, capabilities) VALUES (?, ?, ?)",
                        (name, desc, json.dumps(caps, ensure_ascii=False)),
                    )
            ensure_dev_department(conn)
            _ensure_hr_sessions_columns(conn)
            _ensure_tasks_project_id_column(conn)
            _ensure_planning_sessions_columns(conn)
            _migrate_тимлид_to_dev_lead(conn)
            conn.execute("COMMIT")
        finally:
            conn.close()
    return path


# === Конверсии row → dict ===


def _row_to_task(row: sqlite3.Row) -> dict[str, Any]:
    keys = row.keys() if hasattr(row, "keys") else []
    return {
        "id": row["id"],
        "title": row["title"],
        "description": row["description"],
        "status": row["status"],
        "assignee": row["assignee"],
        "reporter": row["reporter"],
        "priority": row["priority"],
        "labels": json.loads(row["labels"] or "[]"),
        "parent_id": row["parent_id"],
        "requires_approval": bool(row["requires_approval"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "due_at": row["due_at"],
        "completed_at": row["completed_at"],
        "result": json.loads(row["result"]) if row["result"] else None,
        "department_id": row["department_id"] if "department_id" in keys else None,
        # S11.1 (ADR-005): inter-department поля. NULL для intra/legacy задач.
        "requester_department_id": row["requester_department_id"] if "requester_department_id" in keys else None,
        "requester_role_slug": row["requester_role_slug"] if "requester_role_slug" in keys else None,
        # S15.2 (ADR-006): hint для роутера — opus/sonnet/haiku или None.
        "model_hint": row["model_hint"] if "model_hint" in keys else None,
        # F2.1: чекбокс на todo-карточке. DEFAULT 1 (активна).
        "enabled": bool(row["enabled"]) if "enabled" in keys else True,
        # Связь с проектом (PRJ-NNN) — None если задача не привязана.
        "project_id": row["project_id"] if "project_id" in keys else None,
    }


def _row_to_comment(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "task_id": row["task_id"],
        "author": row["author"],
        "text": row["text"],
        "created_at": row["created_at"],
    }


def _row_to_role(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "name": row["name"],
        "description": row["description"],
        "capabilities": json.loads(row["capabilities"] or "[]"),
    }


# === CRUD ===

_ALLOWED_UPDATE_FIELDS = {
    "title",
    "description",
    "status",
    "assignee",
    "priority",
    "labels",
    "due_at",
    "completed_at",
    "requires_approval",
    "model_hint",  # S15.2 (ADR-006): hint для роутера
    "enabled",     # F2.1: чекбокс на todo-карточке
}


def insert_task(
    db_path: Path,
    *,
    title: str,
    description: str = "",
    assignee: Optional[str] = None,
    reporter: Optional[str] = None,
    priority: str = "P2",
    parent_id: Optional[str] = None,
    requires_approval: bool = False,
    status: str = "todo",
    labels: Optional[list[str]] = None,
    department_id: Optional[str] = "dev",
    requester_department_id: Optional[str] = None,
    requester_role_slug: Optional[str] = None,
    model_hint: Optional[str] = None,
    project_id: Optional[int] = None,
) -> dict[str, Any]:
    """Вставка задачи. Возвращает dict как _row_to_task.

    requester_department_id / requester_role_slug — S11.1 (ADR-005), для
    inter-department задач. NULL для обычных intra-задач.
    model_hint — S15.2 (ADR-006): hint для роутера (opus/sonnet/haiku). NULL = авто.
    project_id — связь с таблицей projects (PRJ-NNN). NULL для несвязанных задач.
    """

    task_id = uuid.uuid4().hex[:12]
    now = int(time.time())
    with write_lock(db_path):
        conn = _connect(db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO tasks (
                  id, title, description, status, assignee, reporter, priority,
                  labels, parent_id, requires_approval, created_at, updated_at,
                  department_id, requester_department_id, requester_role_slug,
                  model_hint, project_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    title,
                    description,
                    status,
                    assignee,
                    reporter,
                    priority,
                    json.dumps(labels or [], ensure_ascii=False),
                    parent_id,
                    1 if requires_approval else 0,
                    now,
                    now,
                    department_id,
                    requester_department_id,
                    requester_role_slug,
                    model_hint,
                    project_id,
                ),
            )
            conn.execute("COMMIT")
            cur = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            return _row_to_task(cur.fetchone())
        finally:
            conn.close()


def get_task(db_path: Path, task_id: str, *, with_history: bool = False) -> Optional[dict[str, Any]]:
    """Прочитать задачу. with_history=True добавит ключи 'comments' и 'subtasks'."""

    conn = _connect(db_path)
    try:
        cur = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = cur.fetchone()
        if row is None:
            return None
        task = _row_to_task(row)
        if with_history:
            cur = conn.execute(
                "SELECT * FROM task_comments WHERE task_id = ? ORDER BY id ASC",
                (task_id,),
            )
            task["comments"] = [_row_to_comment(r) for r in cur.fetchall()]
            cur = conn.execute(
                "SELECT * FROM tasks WHERE parent_id = ? ORDER BY created_at ASC",
                (task_id,),
            )
            task["subtasks"] = [_row_to_task(r) for r in cur.fetchall()]
            # Зависимости тоже в один заход — UI карточки их сразу показывает.
            task["blocked_by"] = get_blockers(db_path, task_id)
            task["blocking"] = get_blocking(db_path, task_id)
        return task
    finally:
        conn.close()


def list_tasks(
    db_path: Path,
    *,
    status: Optional[str] = None,
    assignee: Optional[str] = None,
    label: Optional[str] = None,
    limit: int = 50,
    department_id: Optional[str] = None,
    _filter_department: bool = False,
) -> list[dict[str, Any]]:
    """Список задач с фильтрами. label — substring по JSON-массиву labels.

    department_id + _filter_department=True → фильтр по отделу.
    Если _filter_department=False (по умолчанию) — фильтр по отделу не применяется.
    """

    sql = "SELECT * FROM tasks WHERE 1=1"
    args: list[Any] = []
    if status:
        sql += " AND status = ?"
        args.append(status)
    if assignee:
        sql += " AND assignee = ?"
        args.append(assignee)
    if label:
        # JSON-substring — для MVP достаточно. Идеально было бы json_each, но это сложнее.
        sql += " AND labels LIKE ?"
        args.append(f'%"{label}"%')
    if _filter_department:
        if department_id is None:
            sql += " AND department_id IS NULL"
        else:
            sql += " AND department_id = ?"
            args.append(department_id)
    sql += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    conn = _connect(db_path)
    try:
        cur = conn.execute(sql, args)
        return [_row_to_task(r) for r in cur.fetchall()]
    finally:
        conn.close()


def update_task(db_path: Path, task_id: str, **fields: Any) -> Optional[dict[str, Any]]:
    """Обновление полей задачи. Только из _ALLOWED_UPDATE_FIELDS."""

    bad = set(fields) - _ALLOWED_UPDATE_FIELDS
    if bad:
        raise ValueError(f"Недопустимые поля: {sorted(bad)}")
    if not fields:
        return get_task(db_path, task_id)

    sets = []
    args: list[Any] = []
    for key, value in fields.items():
        if key == "labels":
            sets.append("labels = ?")
            args.append(json.dumps(value or [], ensure_ascii=False))
        elif key in ("requires_approval", "enabled"):
            sets.append(f"{key} = ?")
            args.append(1 if value else 0)
        else:
            sets.append(f"{key} = ?")
            args.append(value)
    now = int(time.time())
    sets.append("updated_at = ?")
    args.append(now)
    if fields.get("status") == "done":
        sets.append("completed_at = ?")
        args.append(now)
    args.append(task_id)

    with write_lock(db_path):
        conn = _connect(db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?",
                args,
            )
            if cur.rowcount == 0:
                conn.execute("ROLLBACK")
                return None
            conn.execute("COMMIT")
            cur = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            return _row_to_task(cur.fetchone())
        finally:
            conn.close()


def claim_task(db_path: Path, task_id: str, assignee: str) -> dict[str, Any]:
    """Атомарно взять задачу в работу.

    Возвращает dict со ключом 'ok': True/False.
    ok=False — задача уже у другого assignee (conflict) или не существует.
    Используется бэкендом/qa при старте работы, чтобы не было двойного захвата.
    """

    with write_lock(db_path):
        conn = _connect(db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            row = cur.fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                return {"ok": False, "reason": "not_found", "task_id": task_id}
            current = row["assignee"]
            if current and current != assignee:
                conn.execute("ROLLBACK")
                return {
                    "ok": False,
                    "reason": "conflict",
                    "task_id": task_id,
                    "current_assignee": current,
                }
            now = int(time.time())
            conn.execute(
                "UPDATE tasks SET assignee = ?, status = ?, updated_at = ? WHERE id = ?",
                (assignee, "wip", now, task_id),
            )
            conn.execute("COMMIT")
            cur = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            return {"ok": True, "task": _row_to_task(cur.fetchone())}
        finally:
            conn.close()


def add_comment(db_path: Path, task_id: str, author: str, text: str) -> dict[str, Any]:
    """Добавить запись в task_comments."""

    now = int(time.time())
    with write_lock(db_path):
        conn = _connect(db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute("SELECT id FROM tasks WHERE id = ?", (task_id,))
            if cur.fetchone() is None:
                conn.execute("ROLLBACK")
                raise KeyError(f"task {task_id} не существует")
            cur = conn.execute(
                "INSERT INTO task_comments (task_id, author, text, created_at) VALUES (?, ?, ?, ?)",
                (task_id, author, text, now),
            )
            comment_id = cur.lastrowid
            conn.execute(
                "UPDATE tasks SET updated_at = ? WHERE id = ?",
                (now, task_id),
            )
            conn.execute("COMMIT")
            cur = conn.execute("SELECT * FROM task_comments WHERE id = ?", (comment_id,))
            return _row_to_comment(cur.fetchone())
        finally:
            conn.close()


def submit_result(
    db_path: Path,
    task_id: str,
    result: dict[str, Any],
    new_status: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Сохранить результат подзадачи. Опционально сменить статус."""

    now = int(time.time())
    with write_lock(db_path):
        conn = _connect(db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute("SELECT id FROM tasks WHERE id = ?", (task_id,))
            if cur.fetchone() is None:
                conn.execute("ROLLBACK")
                return None
            if new_status:
                if new_status == "done":
                    conn.execute(
                        "UPDATE tasks SET result = ?, status = ?, updated_at = ?, completed_at = ? WHERE id = ?",
                        (json.dumps(result, ensure_ascii=False), new_status, now, now, task_id),
                    )
                else:
                    conn.execute(
                        "UPDATE tasks SET result = ?, status = ?, updated_at = ? WHERE id = ?",
                        (json.dumps(result, ensure_ascii=False), new_status, now, task_id),
                    )
            else:
                conn.execute(
                    "UPDATE tasks SET result = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(result, ensure_ascii=False), now, task_id),
                )
            conn.execute("COMMIT")
            cur = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            return _row_to_task(cur.fetchone())
        finally:
            conn.close()


def list_roles(db_path: Path) -> list[dict[str, Any]]:
    conn = _connect(db_path)
    try:
        cur = conn.execute("SELECT * FROM roles ORDER BY name ASC")
        return [_row_to_role(r) for r in cur.fetchall()]
    finally:
        conn.close()


def post_chat_message(
    db_path: Path,
    author: str,
    text: str,
    department_id: Optional[str] = "dev",
) -> dict[str, Any]:
    """Постит сообщение в чат. department_id=None → глобальный межотдельный канал."""
    _base_allowed = {
        "пользователь", "тимлид", "бэкенд", "qa",
        "архитектор", "frontend", "devops", "техписатель",
        "system", "managing-director", "owner",
    }
    _db_roles: set[str] = set()
    try:
        _conn = _connect(db_path)
        try:
            _rows = _conn.execute("SELECT name FROM roles").fetchall()
            _db_roles = {r["name"] for r in _rows}
        finally:
            _conn.close()
    except Exception:  # noqa: BLE001
        pass
    _allowed = _base_allowed | _db_roles
    if author not in _allowed:
        raise ValueError(f"неизвестный author: {author}")
    if not text or not text.strip():
        raise ValueError("text пустой")
    now = int(time.time())
    with write_lock(db_path):
        conn = _connect(db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                "INSERT INTO chat_messages (author, text, created_at, department_id) VALUES (?, ?, ?, ?)",
                (author, text.strip(), now, department_id),
            )
            mid = cur.lastrowid
            conn.execute("COMMIT")
            cur = conn.execute("SELECT * FROM chat_messages WHERE id = ?", (mid,))
            r = cur.fetchone()
            return {
                "id": r["id"],
                "author": r["author"],
                "text": r["text"],
                "created_at": r["created_at"],
                "department_id": r["department_id"],
            }
        finally:
            conn.close()


def list_chat_messages(
    db_path: Path,
    *,
    since: int = 0,
    limit: int = 100,
    department_id: Optional[str] = "dev",
) -> list[dict[str, Any]]:
    """Лента чата. since — unix-ts, limit — максимум сообщений.
    department_id=None → глобальный канал (WHERE department_id IS NULL).
    """
    conn = _connect(db_path)
    try:
        if department_id is None:
            cur = conn.execute(
                "SELECT * FROM chat_messages WHERE created_at >= ? AND department_id IS NULL ORDER BY id ASC LIMIT ?",
                (since, limit),
            )
        else:
            cur = conn.execute(
                "SELECT * FROM chat_messages WHERE created_at >= ? AND department_id = ? ORDER BY id ASC LIMIT ?",
                (since, department_id, limit),
            )
        return [
            {
                "id": r["id"],
                "author": r["author"],
                "text": r["text"],
                "created_at": r["created_at"],
                "department_id": r["department_id"],
                "thread_id": r["thread_id"] if "thread_id" in r.keys() else None,
            }
            for r in cur.fetchall()
        ]
    finally:
        conn.close()


# === Chat Threads (Phase 3a B2) ===


def create_chat_thread(
    db_path: Path,
    title: str,
    kind: str = "direct",
    participants: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Создать новый thread для планёрки (ADR-011 §2.3).

    Args:
        title: название потока (строка).
        kind: тип ('direct' или 'planning').
        participants: список участников (опционально, по умолчанию пустой array).

    Returns:
        dict с полями: id, title, kind, participants, status, created_at, updated_at.
    """
    thread_id = str(uuid.uuid4())
    now = int(time.time())
    if participants is None:
        participants = []

    with write_lock(db_path):
        conn = _connect(db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO chat_threads (id, title, kind, participants, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (thread_id, title, kind, json.dumps(participants), "active", now, now),
            )
            conn.commit()

            row = conn.execute(
                "SELECT * FROM chat_threads WHERE id = ?",
                (thread_id,),
            ).fetchone()
            return {
                "id": row["id"],
                "title": row["title"],
                "kind": row["kind"],
                "participants": json.loads(row["participants"]),
                "status": row["status"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        finally:
            conn.close()


def list_chat_threads(
    db_path: Path,
    status: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Получить список threads.

    Args:
        status: фильтр по статусу ('active' или 'archived'). None → все.

    Returns:
        list[dict] с полями: id, title, kind, participants, status, created_at, finished_at,
                  отсортировано по updated_at DESC.
    """
    conn = _connect(db_path)
    try:
        if status is None:
            cur = conn.execute(
                """
                SELECT * FROM chat_threads
                ORDER BY updated_at DESC
                """
            )
        else:
            cur = conn.execute(
                """
                SELECT * FROM chat_threads
                WHERE status = ?
                ORDER BY updated_at DESC
                """,
                (status,),
            )

        result = []
        for row in cur.fetchall():
            participants_str = row["participants"]
            finished_at = row["finished_at"]
            result.append({
                "id": row["id"],
                "title": row["title"],
                "kind": row["kind"],
                "participants": json.loads(participants_str or "[]"),
                "status": row["status"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "finished_at": finished_at,
            })
        return result
    finally:
        conn.close()


def get_chat_thread(db_path: Path, thread_id: str) -> Optional[dict[str, Any]]:
    """Получить thread по ID."""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM chat_threads WHERE id = ?",
            (thread_id,),
        ).fetchone()
        if row is None:
            return None

        participants_str = row["participants"]
        finished_at = row["finished_at"]
        return {
            "id": row["id"],
            "title": row["title"],
            "kind": row["kind"],
            "participants": json.loads(participants_str or "[]"),
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "finished_at": finished_at,
        }
    finally:
        conn.close()


def add_chat_message_to_thread(
    db_path: Path,
    thread_id: str,
    author: str,
    text: str,
) -> dict[str, Any]:
    """Добавить сообщение в thread.

    Args:
        thread_id: ID потока (должен существовать).
        author: автор (роль).
        text: текст сообщения.

    Returns:
        dict с полями: id, author, text, created_at, thread_id.

    Raises:
        ValueError: если thread не существует или author неизвестен.
    """
    # Базовый набор ролей + любая роль из БД
    _base_allowed = {
        "пользователь", "тимлид", "бэкенд", "qa",
        "архитектор", "frontend", "devops", "техписатель",
        "system", "managing-director", "owner",
    }

    # Загружаем все роли из БД
    _db_roles = set()
    try:
        conn_roles = _connect(db_path)
        try:
            rows = conn_roles.execute("SELECT name FROM roles").fetchall()
            _db_roles = {row["name"] for row in rows}
        finally:
            conn_roles.close()
    except Exception:  # noqa: BLE001
        pass  # Если ошибка — используем только базовый набор

    _allowed = _base_allowed | _db_roles
    if author not in _allowed:
        raise ValueError(f"неизвестный author: {author}")
    if not text or not text.strip():
        raise ValueError("text пустой")

    # Проверяем что thread существует.
    thread = get_chat_thread(db_path, thread_id)
    if thread is None:
        raise ValueError(f"thread {thread_id!r} не найден")

    now = int(time.time())
    with write_lock(db_path):
        conn = _connect(db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                "INSERT INTO chat_messages (author, text, created_at, thread_id) VALUES (?, ?, ?, ?)",
                (author, text.strip(), now, thread_id),
            )
            msg_id = cur.lastrowid
            conn.commit()

            row = conn.execute(
                "SELECT * FROM chat_messages WHERE id = ?",
                (msg_id,),
            ).fetchone()
            return {
                "id": row["id"],
                "author": row["author"],
                "text": row["text"],
                "created_at": row["created_at"],
                "thread_id": row["thread_id"],
            }
        finally:
            conn.close()


def get_thread_messages(
    db_path: Path,
    thread_id: str,
    viewer: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Получить сообщения thread'а.

    Args:
        thread_id: ID потока.
        viewer: 'owner' или 'managing-director' или None.
                Если 'owner': исключает сообщения от тимлид-ролей
                (тимлид, лид-ов специалистов и других лидов).

    Returns:
        list[dict] с полями: id, author, text, created_at, thread_id.
    """
    # ADR-011 §6.1: viewer='owner' прячет реплики тимлидов в обычных тредах,
    # чтобы они не шумели в чате owner-а. НО в planning-тредах реплики лидов —
    # это и есть содержимое планёрки, owner должен их видеть. Поэтому фильтр
    # применяем только если thread.kind != 'planning'.
    apply_lead_filter = False
    lead_roles: set[str] = set()
    if viewer == "owner":
        thread = get_chat_thread(db_path, thread_id)
        if thread is not None and thread.get("kind") != "planning":
            apply_lead_filter = True
            conn_roles = _connect(db_path)
            try:
                rows = conn_roles.execute("SELECT name FROM roles WHERE name LIKE '%lead'").fetchall()
                lead_roles = {row["name"] for row in rows}
                lead_roles.add("тимлид")
            finally:
                conn_roles.close()

    conn = _connect(db_path)
    try:
        if apply_lead_filter and lead_roles:
            cur = conn.execute(
                """
                SELECT * FROM chat_messages
                WHERE thread_id = ? AND author NOT IN ({})
                ORDER BY created_at ASC
                """.format(",".join("?" * len(lead_roles))),
                [thread_id] + list(lead_roles),
            )
        else:
            cur = conn.execute(
                "SELECT * FROM chat_messages WHERE thread_id = ? ORDER BY created_at ASC",
                (thread_id,),
            )

        return [
            {
                "id": r["id"],
                "author": r["author"],
                "text": r["text"],
                "created_at": r["created_at"],
                "thread_id": r["thread_id"],
            }
            for r in cur.fetchall()
        ]
    finally:
        conn.close()


def update_chat_thread_status(
    db_path: Path,
    thread_id: str,
    status: str,
) -> Optional[dict[str, Any]]:
    """Обновить статус thread'а.

    Args:
        thread_id: ID потока.
        status: 'active', 'archived', или 'aborted'.

    Returns:
        dict с обновленными данными thread'а или None если не найден.
    """
    allowed_statuses = {"active", "archived", "aborted"}
    if status not in allowed_statuses:
        raise ValueError(f"неизвестный статус: {status}")

    now = int(time.time())
    finished_at = now if status in ("archived", "aborted") else None

    with write_lock(db_path):
        conn = _connect(db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE chat_threads SET status = ?, finished_at = ? WHERE id = ?",
                (status, finished_at, thread_id),
            )
            conn.commit()

            row = conn.execute(
                "SELECT * FROM chat_threads WHERE id = ?",
                (thread_id,),
            ).fetchone()
            if row is None:
                return None

            participants_str = row["participants"]
            finished_at = row["finished_at"]
            return {
                "id": row["id"],
                "title": row["title"],
                "kind": row["kind"],
                "participants": json.loads(participants_str or "[]"),
                "status": row["status"],
                "created_at": row["created_at"],
                "finished_at": finished_at,
            }
        finally:
            conn.close()


# === Departments helpers ===


def _row_to_department(row: sqlite3.Row) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "template_id": row["template_id"],
        "icon": row["icon"],
        "created_at": row["created_at"],
        "archived_at": row["archived_at"],
    }
    # counts — опциональные поля если запрос включал агрегаты
    keys = row.keys() if hasattr(row, "keys") else []
    if "tasks_open" in keys:
        d["tasks_open"] = row["tasks_open"]
    if "tasks_total" in keys:
        d["tasks_total"] = row["tasks_total"]
    return d


def list_departments(
    db_path: Path,
    *,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    """Список отделов с counts (tasks_open, tasks_total)."""
    conn = _connect(db_path)
    try:
        where = "" if include_archived else "WHERE d.archived_at IS NULL"
        cur = conn.execute(
            f"""
            SELECT d.*,
              COUNT(DISTINCT CASE WHEN t.status IN ('todo','wip') THEN t.id END) AS tasks_open,
              COUNT(DISTINCT t.id) AS tasks_total
            FROM departments d
            LEFT JOIN tasks t ON t.department_id = d.id
            {where}
            GROUP BY d.id
            ORDER BY d.name ASC
            """
        )
        return [_row_to_department(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_department(db_path: Path, dept_id: str) -> Optional[dict[str, Any]]:
    """Метаданные отдела + список ролей, привязанных к нему."""
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            """
            SELECT d.*,
              COUNT(DISTINCT CASE WHEN t.status IN ('todo','wip') THEN t.id END) AS tasks_open,
              COUNT(DISTINCT t.id) AS tasks_total
            FROM departments d
            LEFT JOIN tasks t ON t.department_id = d.id
            WHERE d.id = ?
            GROUP BY d.id
            """,
            (dept_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        dept = _row_to_department(row)
        # Роли этого отдела
        cur = conn.execute(
            "SELECT * FROM roles WHERE department_id = ? ORDER BY name ASC",
            (dept_id,),
        )
        dept["roles"] = [_row_to_role(r) for r in cur.fetchall()]
        return dept
    finally:
        conn.close()


def create_department(
    db_path: Path,
    *,
    dept_id: str,
    name: str,
    description: str = "",
    template_id: Optional[str] = None,
    icon: str = "🗂",
) -> dict[str, Any]:
    """Создать новый отдел. Ошибка если id или name уже занят."""
    now = int(time.time())
    with write_lock(db_path):
        conn = _connect(db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            # Проверяем уникальность id и name
            existing_id = conn.execute(
                "SELECT id FROM departments WHERE id = ?", (dept_id,)
            ).fetchone()
            if existing_id is not None:
                conn.execute("ROLLBACK")
                raise ValueError(f"Отдел с id={dept_id!r} уже существует")
            existing_name = conn.execute(
                "SELECT id FROM departments WHERE name = ?", (name,)
            ).fetchone()
            if existing_name is not None:
                conn.execute("ROLLBACK")
                raise ValueError(f"Отдел с name={name!r} уже существует")
            conn.execute(
                """
                INSERT INTO departments (id, name, description, template_id, icon, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (dept_id, name, description, template_id, icon, now),
            )
            conn.execute("COMMIT")
            cur = conn.execute("SELECT * FROM departments WHERE id = ?", (dept_id,))
            row = cur.fetchone()
            return _row_to_department(row)
        finally:
            conn.close()


def record_claude_session(
    db_path: Path,
    *,
    started_at: int,
    finished_at: int,
    duration_ms: Optional[int] = None,
    num_turns: Optional[int] = None,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    total_cost_usd: Optional[float] = None,
    model: Optional[str] = None,
    is_error: bool = False,
) -> int:
    """Записать факт прохождения Claude-сессии (приходит из stream-json events).

    Используется дашбордом для счётчика usage в шапке. Источник — событие
    type=result от `claude --output-format stream-json`.
    """
    with write_lock(db_path):
        conn = _connect(db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                """
                INSERT INTO claude_sessions (
                  started_at, finished_at, duration_ms, num_turns,
                  input_tokens, output_tokens, total_cost_usd, model, is_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    started_at,
                    finished_at,
                    duration_ms,
                    num_turns,
                    input_tokens,
                    output_tokens,
                    total_cost_usd,
                    model,
                    1 if is_error else 0,
                ),
            )
            sid = cur.lastrowid
            conn.execute("COMMIT")
            return sid
        finally:
            conn.close()


def usage_summary(db_path: Path) -> dict[str, Any]:
    """Агрегированный usage Claude по разным окнам.

    Возвращает sessions/turns/input/output/cost для:
    last_5h, today, last_24h, total. Все суммы — int/float, никаких NULL.
    """
    now = int(time.time())
    # Сегодня = с 00:00 локального дня. Для простоты: округление now до суток UTC.
    midnight = (now // 86400) * 86400
    windows = {
        "last_5h": now - 5 * 3600,
        "today": midnight,
        "last_24h": now - 24 * 3600,
    }
    conn = _connect(db_path)
    try:
        result: dict[str, Any] = {}
        for label, since in windows.items():
            row = conn.execute(
                """
                SELECT
                  COUNT(*) AS sessions,
                  COALESCE(SUM(num_turns), 0)      AS turns,
                  COALESCE(SUM(input_tokens), 0)   AS input_tokens,
                  COALESCE(SUM(output_tokens), 0)  AS output_tokens,
                  COALESCE(SUM(total_cost_usd), 0) AS cost_usd
                FROM claude_sessions
                WHERE finished_at >= ?
                """,
                (since,),
            ).fetchone()
            result[label] = {
                "sessions": row["sessions"],
                "turns": row["turns"],
                "input_tokens": row["input_tokens"],
                "output_tokens": row["output_tokens"],
                "cost_usd": round(row["cost_usd"], 4),
            }
        row = conn.execute(
            """
            SELECT
              COUNT(*) AS sessions,
              COALESCE(SUM(num_turns), 0)      AS turns,
              COALESCE(SUM(input_tokens), 0)   AS input_tokens,
              COALESCE(SUM(output_tokens), 0)  AS output_tokens,
              COALESCE(SUM(total_cost_usd), 0) AS cost_usd
            FROM claude_sessions
            """
        ).fetchone()
        result["total"] = {
            "sessions": row["sessions"],
            "turns": row["turns"],
            "input_tokens": row["input_tokens"],
            "output_tokens": row["output_tokens"],
            "cost_usd": round(row["cost_usd"], 4),
        }
        # Топ-3 моделей
        rows = conn.execute(
            """
            SELECT model, COUNT(*) AS n, COALESCE(SUM(num_turns), 0) AS turns
            FROM claude_sessions
            WHERE model IS NOT NULL
            GROUP BY model
            ORDER BY turns DESC
            LIMIT 3
            """
        ).fetchall()
        result["models"] = [
            {"model": r["model"], "sessions": r["n"], "turns": r["turns"]}
            for r in rows
        ]
        return result
    finally:
        conn.close()


def add_dependency(db_path: Path, task_id: str, depends_on: str) -> dict[str, Any]:
    """Объявить что task_id блокируется задачей depends_on.

    Возвращает {ok, reason} — false если самозависимость, цикл, или
    одна из задач не существует.
    """
    if task_id == depends_on:
        return {"ok": False, "reason": "самозависимость"}
    db_path = Path(db_path)  # tolerant к строке
    now = int(time.time())
    with write_lock(db_path):
        conn = _connect(db_path)
        try:
            for tid in (task_id, depends_on):
                if conn.execute("SELECT 1 FROM tasks WHERE id = ?", (tid,)).fetchone() is None:
                    return {"ok": False, "reason": f"задача {tid} не существует"}
            # Проверка цикла: BFS от depends_on по его собственным blockers.
            # Если дойдём до task_id — будет цикл.
            seen = {depends_on}
            queue = [depends_on]
            while queue:
                cur_id = queue.pop()
                cur = conn.execute(
                    "SELECT depends_on FROM task_dependencies WHERE task_id = ?", (cur_id,)
                ).fetchall()
                for (next_id,) in cur:
                    if next_id == task_id:
                        return {"ok": False, "reason": "цикл зависимости"}
                    if next_id not in seen:
                        seen.add(next_id)
                        queue.append(next_id)
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT OR IGNORE INTO task_dependencies (task_id, depends_on, created_at) "
                "VALUES (?, ?, ?)",
                (task_id, depends_on, now),
            )
            conn.execute("COMMIT")
            return {"ok": True}
        finally:
            conn.close()


def remove_dependency(db_path: Path, task_id: str, depends_on: str) -> bool:
    with write_lock(db_path):
        conn = _connect(db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                "DELETE FROM task_dependencies WHERE task_id = ? AND depends_on = ?",
                (task_id, depends_on),
            )
            conn.execute("COMMIT")
            return cur.rowcount > 0
        finally:
            conn.close()


def get_blockers(db_path: Path, task_id: str) -> list[dict[str, Any]]:
    """Задачи, которые блокируют task_id (depends_on). Только незакрытые."""
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            """
            SELECT t.* FROM task_dependencies d
            JOIN tasks t ON t.id = d.depends_on
            WHERE d.task_id = ? AND t.status NOT IN ('done', 'blocked')
            ORDER BY t.created_at ASC
            """,
            (task_id,),
        )
        return [_row_to_task(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_blocking(db_path: Path, task_id: str) -> list[dict[str, Any]]:
    """Задачи, которые блокируются task_id."""
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            """
            SELECT t.* FROM task_dependencies d
            JOIN tasks t ON t.id = d.task_id
            WHERE d.depends_on = ? AND t.status NOT IN ('done', 'blocked')
            ORDER BY t.created_at ASC
            """,
            (task_id,),
        )
        return [_row_to_task(r) for r in cur.fetchall()]
    finally:
        conn.close()


def is_blocked(db_path: Path, task_id: str) -> bool:
    """True если есть незакрытые blockers."""
    return len(get_blockers(db_path, task_id)) > 0


def insert_system_comment(db_path: Path, task_id: str, text: str) -> dict[str, Any]:
    """Добавить системный комментарий (author='system') без проверки роли.

    Используется safety-net'ом в tools.py когда кто-то пытается выставить
    status=done через MCP. Не кидает исключений если задача не найдена —
    просто возвращает пустой dict.
    """
    now = int(time.time())
    with write_lock(db_path):
        conn = _connect(db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute("SELECT id FROM tasks WHERE id = ?", (task_id,))
            if cur.fetchone() is None:
                conn.execute("ROLLBACK")
                return {}
            cur = conn.execute(
                "INSERT INTO task_comments (task_id, author, text, created_at) VALUES (?, ?, ?, ?)",
                (task_id, "system", text, now),
            )
            comment_id = cur.lastrowid
            conn.execute(
                "UPDATE tasks SET updated_at = ? WHERE id = ?",
                (now, task_id),
            )
            conn.execute("COMMIT")
            cur = conn.execute("SELECT * FROM task_comments WHERE id = ?", (comment_id,))
            return _row_to_comment(cur.fetchone())
        finally:
            conn.close()


# === HR sessions (S10.3, ADR-004) ===


_HR_VALID_STATES = (
    "hr_planning",
    "awaiting_owner_review",
    "hr_revising",
    "hr_activating",
    "active",
    "aborted",
)


def _row_to_hr_session(row: sqlite3.Row) -> dict[str, Any]:
    """sqlite3.Row → dict для hr_sessions."""
    keys = row.keys() if hasattr(row, "keys") else []
    plan_raw = row["plan_json"] if "plan_json" in keys else None
    try:
        plan = json.loads(plan_raw) if plan_raw else None
    except (json.JSONDecodeError, TypeError):
        plan = None
    return {
        "id":               row["id"],
        "department_name":  row["department_name"],
        "state":            row["state"],
        "plan":             plan,
        "plan_json":        plan_raw,
        "template_hint":    row["template_hint"] if "template_hint" in keys else None,
        "started_at":       row["started_at"] if "started_at" in keys else None,
        "finished_at":      row["finished_at"] if "finished_at" in keys else None,
        "iteration_count":  row["iteration_count"] if "iteration_count" in keys else 0,
        "last_message":     row["last_message"] if "last_message" in keys else None,
        "attempt_count":    row["attempt_count"] if "attempt_count" in keys else 0,
    }


def create_hr_session(
    db_path: Path,
    *,
    department_name: str,
    template_hint: Optional[str] = None,
    state: str = "hr_planning",
) -> dict[str, Any]:
    """Создаёт новую запись hr_sessions, возвращает её dict.

    id — uuid4 hex[:12]. started_at — now(). iteration_count=0, attempt_count=0.
    """
    if not department_name or not department_name.strip():
        raise ValueError("department_name пустой")
    if state not in _HR_VALID_STATES:
        raise ValueError(f"невалидное state: {state!r}")
    session_id = uuid.uuid4().hex[:12]
    now = int(time.time())
    with write_lock(db_path):
        conn = _connect(db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO hr_sessions (
                  id, department_name, state, plan_json, template_hint,
                  started_at, finished_at, iteration_count, last_message,
                  attempt_count
                ) VALUES (?, ?, ?, NULL, ?, ?, NULL, 0, NULL, 0)
                """,
                (session_id, department_name.strip(), state, template_hint, now),
            )
            conn.execute("COMMIT")
            cur = conn.execute(
                "SELECT * FROM hr_sessions WHERE id = ?", (session_id,)
            )
            return _row_to_hr_session(cur.fetchone())
        finally:
            conn.close()


def get_hr_session(db_path: Path, session_id: str) -> Optional[dict[str, Any]]:
    """Прочитать hr_session по id. None если не найдена."""
    conn = _connect(db_path)
    try:
        cur = conn.execute("SELECT * FROM hr_sessions WHERE id = ?", (session_id,))
        row = cur.fetchone()
        if row is None:
            return None
        return _row_to_hr_session(row)
    finally:
        conn.close()


_HR_ALLOWED_UPDATE_FIELDS = {
    "state",
    "plan_json",
    "iteration_count",
    "last_message",
    "attempt_count",
    "finished_at",
}


def update_hr_session(
    db_path: Path, session_id: str, **fields: Any
) -> Optional[dict[str, Any]]:
    """Обновить поля hr_session. Безопасные поля — из _HR_ALLOWED_UPDATE_FIELDS.

    `state` валидируется по _HR_VALID_STATES. Возвращает обновлённый dict
    или None если сессия не найдена.
    """
    if not fields:
        return get_hr_session(db_path, session_id)

    bad = set(fields) - _HR_ALLOWED_UPDATE_FIELDS
    if bad:
        raise ValueError(f"Недопустимые поля hr_session: {sorted(bad)}")

    if "state" in fields and fields["state"] not in _HR_VALID_STATES:
        raise ValueError(f"невалидное state: {fields['state']!r}")

    sets: list[str] = []
    args: list[Any] = []
    for key, value in fields.items():
        sets.append(f"{key} = ?")
        args.append(value)
    args.append(session_id)

    with write_lock(db_path):
        conn = _connect(db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                f"UPDATE hr_sessions SET {', '.join(sets)} WHERE id = ?",
                args,
            )
            if cur.rowcount == 0:
                conn.execute("ROLLBACK")
                return None
            conn.execute("COMMIT")
            cur = conn.execute(
                "SELECT * FROM hr_sessions WHERE id = ?", (session_id,)
            )
            return _row_to_hr_session(cur.fetchone())
        finally:
            conn.close()


def delete_task(db_path: Path, task_id: str) -> bool:
    """Удаляет задачу (только для тестов и админ-операций)."""

    with write_lock(db_path):
        conn = _connect(db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM task_comments WHERE task_id = ?", (task_id,))
            conn.execute(
                "DELETE FROM task_dependencies WHERE task_id = ? OR depends_on = ?",
                (task_id, task_id),
            )
            cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            conn.execute("COMMIT")
            return cur.rowcount > 0
        finally:
            conn.close()


# === Hook для безопасной модификации (опц.) ===


def atomic_modify(
    db_path: Path,
    task_id: str,
    modifier: Callable[[dict[str, Any]], dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """Read → modify → write одной задачи под write_lock.

    Аналог client_card._atomic_modify. modifier получает dict (как из get_task)
    и возвращает dict с теми полями, которые надо обновить (subset
    _ALLOWED_UPDATE_FIELDS). None из get_task на входе → None на выходе.
    """

    with write_lock(db_path):
        existing = get_task(db_path, task_id)
        if existing is None:
            return None
        patch = modifier(existing)
        if not patch:
            return existing
        bad = set(patch) - _ALLOWED_UPDATE_FIELDS
        if bad:
            raise ValueError(f"modifier вернул недопустимые поля: {sorted(bad)}")
        # NB: update_task внутри тоже берёт write_lock — fcntl re-entrant
        # внутри одного процесса по тому же FD НЕ работает. Поэтому пишем
        # напрямую через _connect/BEGIN IMMEDIATE.
        sets = []
        args: list[Any] = []
        for key, value in patch.items():
            if key == "labels":
                sets.append("labels = ?")
                args.append(json.dumps(value or [], ensure_ascii=False))
            elif key in ("requires_approval", "enabled"):
                sets.append(f"{key} = ?")
                args.append(1 if value else 0)
            else:
                sets.append(f"{key} = ?")
                args.append(value)
        now = int(time.time())
        sets.append("updated_at = ?")
        args.append(now)
        if patch.get("status") == "done":
            sets.append("completed_at = ?")
            args.append(now)
        args.append(task_id)
        conn = _connect(db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?", args)
            conn.execute("COMMIT")
            cur = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            return _row_to_task(cur.fetchone())
        finally:
            conn.close()


# === Manager Memory (B2, ADR-007 §2.1–§2.2) ===
#
# Долгосрочная память Управляющего. Чанки в `manager_chunks` + FTS5 в
# `manager_fts` синхронизируются триггерами (см. SCHEMA_SQL выше). Доступ к
# этим функциям предоставляется только роли `managing-director` через
# role-gate в tools.py (а не на уровне БД — БД-слой остаётся «глупым»).
#
# Все функции иммутабельны по дизайну: update нет; новый факт = новый чанк.
# Soft-delete через колонку `archived_at`.

_MANAGER_VALID_SOURCES: tuple[str, ...] = (
    "conversation",
    "note",
    "recall",
    "planning",
    "import",
)


def _row_to_manager_chunk(row: sqlite3.Row, *, score: Optional[float] = None) -> dict[str, Any]:
    """sqlite3.Row → dict для manager_chunks. score опционален (для FTS-search)."""
    try:
        tags = json.loads(row["tags"] or "[]")
    except (json.JSONDecodeError, TypeError):
        tags = []
    chunk = {
        "id":          row["id"],
        "user_id":     row["user_id"],
        "source":      row["source"],
        "path":        row["path"],
        "start_line":  row["start_line"],
        "end_line":    row["end_line"],
        "text":        row["text"],
        "tags":        tags,
        "created_at":  row["created_at"],
        "updated_at":  row["updated_at"],
        "archived_at": row["archived_at"],
    }
    if score is not None:
        chunk["score"] = score
    return chunk


def manager_chunk_insert(
    db_path: Path,
    *,
    text: str,
    source: str,
    path: Optional[str] = None,
    tags: Optional[list[str]] = None,
    user_id: str = "owner",
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
) -> dict[str, Any]:
    """Создаёт новый чанк памяти. FTS-индексация выполнится триггером AFTER INSERT.

    Возвращает dict как `_row_to_manager_chunk` (без score).
    """
    if not text or not text.strip():
        raise ValueError("text пустой")
    if source not in _MANAGER_VALID_SOURCES:
        raise ValueError(
            f"неизвестный source: {source!r} (ожидается один из {_MANAGER_VALID_SOURCES})"
        )
    tags_json = json.dumps(tags or [], ensure_ascii=False)
    now = int(time.time())
    with write_lock(db_path):
        conn = _connect(db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                """
                INSERT INTO manager_chunks (
                  user_id, source, path, start_line, end_line, text,
                  embedding, tags, created_at, updated_at, archived_at
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, NULL)
                """,
                (
                    user_id,
                    source,
                    path,
                    start_line,
                    end_line,
                    text,
                    tags_json,
                    now,
                    now,
                ),
            )
            chunk_id = cur.lastrowid
            conn.execute("COMMIT")
            cur = conn.execute(
                "SELECT * FROM manager_chunks WHERE id = ?", (chunk_id,)
            )
            return _row_to_manager_chunk(cur.fetchone())
        finally:
            conn.close()


def manager_chunk_get(db_path: Path, chunk_id: int) -> Optional[dict[str, Any]]:
    """Прочитать чанк по id. None если не существует."""
    conn = _connect(db_path)
    try:
        cur = conn.execute("SELECT * FROM manager_chunks WHERE id = ?", (chunk_id,))
        row = cur.fetchone()
        if row is None:
            return None
        return _row_to_manager_chunk(row)
    finally:
        conn.close()


def manager_chunk_search(
    db_path: Path,
    *,
    query: str,
    source: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = 10,
    user_id: str = "owner",
) -> list[dict[str, Any]]:
    """FTS5-поиск чанков. Возвращает список с полем `score` (= bm25, меньше = релевантнее).

    Пустой query → пустой список (FTS5 не любит пустую строку).
    Игнорирует архивные чанки. Может фильтровать по source и/или tag.
    """
    if not query or not query.strip():
        return []
    if source is not None and source not in _MANAGER_VALID_SOURCES:
        raise ValueError(f"неизвестный source: {source!r}")
    limit = max(1, min(int(limit), 100))

    sql = (
        "SELECT c.*, bm25(manager_fts) AS bm25_score "
        "FROM manager_fts "
        "JOIN manager_chunks c ON c.id = manager_fts.rowid "
        "WHERE manager_fts MATCH ? "
        "AND c.archived_at IS NULL "
        "AND c.user_id = ?"
    )
    args: list[Any] = [query, user_id]
    if source is not None:
        sql += " AND c.source = ?"
        args.append(source)
    if tag is not None:
        # tags хранится как JSON-массив, ищем substring `"<tag>"` (с кавычками,
        # чтобы не зацепить префиксы).
        sql += " AND c.tags LIKE ?"
        args.append(f'%"{tag}"%')
    sql += " ORDER BY bm25(manager_fts) ASC LIMIT ?"
    args.append(limit)

    conn = _connect(db_path)
    try:
        try:
            cur = conn.execute(sql, args)
            rows = cur.fetchall()
        except sqlite3.OperationalError:
            return []
        return [_row_to_manager_chunk(r, score=float(r["bm25_score"])) for r in rows]
    finally:
        conn.close()


def manager_chunk_recent(
    db_path: Path,
    *,
    source: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = 20,
    user_id: str = "owner",
) -> list[dict[str, Any]]:
    """Последние N не-архивных чанков, отсортированные по updated_at DESC.

    Можно фильтровать по source и/или tag (точное совпадение элемента JSON-массива tags).
    """
    if source is not None and source not in _MANAGER_VALID_SOURCES:
        raise ValueError(f"неизвестный source: {source!r}")
    limit = max(1, min(int(limit), 200))

    sql = (
        "SELECT * FROM manager_chunks "
        "WHERE archived_at IS NULL AND user_id = ?"
    )
    args: list[Any] = [user_id]
    if source is not None:
        sql += " AND source = ?"
        args.append(source)
    if tag is not None:
        sql += " AND tags LIKE ?"
        args.append(f'%"{tag}"%')
    sql += " ORDER BY updated_at DESC, id DESC LIMIT ?"
    args.append(limit)

    conn = _connect(db_path)
    try:
        cur = conn.execute(sql, args)
        return [_row_to_manager_chunk(r) for r in cur.fetchall()]
    finally:
        conn.close()


def manager_chunks_archive_by_tag(
    db_path: Path,
    *,
    tag: str,
    user_id: str = "owner",
) -> int:
    """Архивировать все не-архивные чанки с заданным тегом. Возвращает количество.

    Используется при archive_project — все заметки с тегом 'project:<code>'
    уходят в архив одним вызовом.
    """
    now = int(time.time())
    with write_lock(db_path):
        conn = _connect(db_path)
        try:
            cur = conn.execute(
                "UPDATE manager_chunks "
                "SET archived_at = ?, updated_at = ? "
                "WHERE archived_at IS NULL AND user_id = ? AND tags LIKE ?",
                (now, now, user_id, f'%"{tag}"%'),
            )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()


def manager_chunk_archive(db_path: Path, chunk_id: int) -> bool:
    """Soft-delete: проставляет archived_at = now(). Возвращает True если запись была изменена.

    False — если чанка нет или он уже архивирован (idempotent semantics).
    """
    now = int(time.time())
    with write_lock(db_path):
        conn = _connect(db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                "UPDATE manager_chunks SET archived_at = ?, updated_at = ? "
                "WHERE id = ? AND archived_at IS NULL",
                (now, now, chunk_id),
            )
            changed = cur.rowcount > 0
            conn.execute("COMMIT")
            return changed
        finally:
            conn.close()


# === Planning sessions (B3, ADR-009 §2.4) ===
#
# Хранят состояние «совещаний» Управляющего: phase, лог обсуждения,
# консолидированный proposal, вопросы owner-у, итоговые cross-task'и.
# Доступ через MCP-tools planning_* — gate на role.name='managing-director'.

_PLANNING_VALID_PHASES: tuple[str, ...] = (
    "gathering",
    "discussion",
    "consolidation",
    "distribution",
    "done",
)


def _row_to_planning_session(row: sqlite3.Row) -> dict[str, Any]:
    """sqlite3.Row → dict для planning_sessions."""
    def _maybe_load(raw: Optional[str]) -> Any:
        if raw is None or raw == "":
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    keys = row.keys() if hasattr(row, "keys") else []
    return {
        "id":                    row["id"],
        "owner_request":         row["owner_request"],
        "phase":                 row["phase"],
        "departments_involved":  _maybe_load(row["departments_involved"]) or [],
        "discussion_log":        _maybe_load(row["discussion_log"]) or [],
        "consolidated_proposal": row["consolidated_proposal"],
        "questions_for_owner":   row["questions_for_owner"],
        "owner_answer":          row["owner_answer"],
        "created_tasks":         _maybe_load(row["created_tasks"]) or [],
        "started_at":            row["started_at"],
        "finished_at":           row["finished_at"],
        # Phase 3b — оркестрация и лимиты.
        "thread_id":             row["thread_id"] if "thread_id" in keys else None,
        "topic":                 row["topic"] if "topic" in keys else None,
        "total_rounds":          row["total_rounds"] if "total_rounds" in keys else 3,
        "current_round":         row["current_round"] if "current_round" in keys else 0,
        "status":                row["status"] if "status" in keys else "pending",
        "cost_limit_usd":        row["cost_limit_usd"] if "cost_limit_usd" in keys else 2.0,
        "cost_so_far_usd":       row["cost_so_far_usd"] if "cost_so_far_usd" in keys else 0.0,
        "decision":              row["decision"] if "decision" in keys else None,
        "decided_at":            row["decided_at"] if "decided_at" in keys else None,
        "decision_comment":      row["decision_comment"] if "decision_comment" in keys else None,
        "model_profile":         row["model_profile"] if "model_profile" in keys else "base",
    }


_PLANNING_VALID_MODEL_PROFILES = {"base", "deep"}


def planning_session_create(
    db_path: Path,
    *,
    owner_request: str,
    departments: list[str],
    phase: str = "gathering",
    thread_id: Optional[str] = None,
    topic: Optional[str] = None,
    total_rounds: int = 3,
    cost_limit_usd: float = 2.0,
    model_profile: str = "base",
) -> dict[str, Any]:
    """Создать запись planning_sessions. id = uuid4 hex[:12]."""
    if not owner_request or not owner_request.strip():
        raise ValueError("owner_request пустой")
    if not isinstance(departments, list) or len(departments) == 0:
        raise ValueError("departments должен быть непустым списком")
    if phase not in _PLANNING_VALID_PHASES:
        raise ValueError(f"невалидная phase: {phase!r}")
    if not (1 <= int(total_rounds) <= 5):
        raise ValueError("total_rounds должен быть от 1 до 5")
    if float(cost_limit_usd) <= 0:
        raise ValueError("cost_limit_usd должен быть положительным")
    if model_profile not in _PLANNING_VALID_MODEL_PROFILES:
        raise ValueError(f"невалидный model_profile: {model_profile!r}")

    session_id = uuid.uuid4().hex[:12]
    now = int(time.time())
    with write_lock(db_path):
        conn = _connect(db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO planning_sessions (
                  id, owner_request, phase, departments_involved,
                  discussion_log, consolidated_proposal, questions_for_owner,
                  owner_answer, created_tasks, started_at, finished_at,
                  thread_id, topic, total_rounds, current_round, status,
                  cost_limit_usd, cost_so_far_usd, model_profile
                ) VALUES (?, ?, ?, ?, '[]', NULL, NULL, NULL, '[]', ?, NULL,
                          ?, ?, ?, 0, 'pending', ?, 0, ?)
                """,
                (
                    session_id,
                    owner_request.strip(),
                    phase,
                    json.dumps(departments, ensure_ascii=False),
                    now,
                    thread_id,
                    (topic or "").strip() or None,
                    int(total_rounds),
                    float(cost_limit_usd),
                    model_profile,
                ),
            )
            conn.execute("COMMIT")
            cur = conn.execute(
                "SELECT * FROM planning_sessions WHERE id = ?", (session_id,)
            )
            return _row_to_planning_session(cur.fetchone())
        finally:
            conn.close()


def planning_session_get(
    db_path: Path, session_id: str
) -> Optional[dict[str, Any]]:
    """Прочитать planning_session по id. None если не найдена."""
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "SELECT * FROM planning_sessions WHERE id = ?", (session_id,)
        )
        row = cur.fetchone()
        if row is None:
            return None
        return _row_to_planning_session(row)
    finally:
        conn.close()


_PLANNING_ALLOWED_UPDATE_FIELDS = {
    "phase",
    "discussion_log",
    "consolidated_proposal",
    "questions_for_owner",
    "owner_answer",
    "created_tasks",
    "finished_at",
    # Phase 3b orchestration:
    "current_round",
    "status",
    "cost_so_far_usd",
    # Stage 3 — owner decision на финальном отчёте.
    "decision",
    "decided_at",
    "decision_comment",
    # Profile (можно поменять до старта — пока pending).
    "model_profile",
}


def planning_session_update(
    db_path: Path, session_id: str, **fields: Any
) -> Optional[dict[str, Any]]:
    """Обновить поля planning_session. JSON-поля сериализуются автоматически."""
    if not fields:
        return planning_session_get(db_path, session_id)

    bad = set(fields) - _PLANNING_ALLOWED_UPDATE_FIELDS
    if bad:
        raise ValueError(f"Недопустимые поля planning_session: {sorted(bad)}")

    if "phase" in fields and fields["phase"] not in _PLANNING_VALID_PHASES:
        raise ValueError(f"невалидная phase: {fields['phase']!r}")

    sets: list[str] = []
    args: list[Any] = []
    for key, value in fields.items():
        if key in ("discussion_log", "created_tasks"):
            sets.append(f"{key} = ?")
            args.append(json.dumps(value if value is not None else [], ensure_ascii=False))
        else:
            sets.append(f"{key} = ?")
            args.append(value)
    args.append(session_id)

    with write_lock(db_path):
        conn = _connect(db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                f"UPDATE planning_sessions SET {', '.join(sets)} WHERE id = ?",
                args,
            )
            if cur.rowcount == 0:
                conn.execute("ROLLBACK")
                return None
            conn.execute("COMMIT")
            cur = conn.execute(
                "SELECT * FROM planning_sessions WHERE id = ?", (session_id,)
            )
            return _row_to_planning_session(cur.fetchone())
        finally:
            conn.close()


def inbox_summary(db_path: Path) -> list[dict[str, Any]]:
    """Агрегат по всем активным отделам для list_all_inboxes (ADR-009 §2.6).

    Для каждого dept: id, name, wip/review/blocked counts, last_chat_msg_time.
    Архивированные отделы исключены.
    """
    conn = _connect(db_path)
    try:
        # Counts по status в одном запросе. LEFT JOIN для отделов без задач.
        rows = conn.execute(
            """
            SELECT d.id AS dept_id, d.name AS dept_name,
              COUNT(DISTINCT CASE WHEN t.status = 'wip'     THEN t.id END) AS wip,
              COUNT(DISTINCT CASE WHEN t.status = 'review'  THEN t.id END) AS review,
              COUNT(DISTINCT CASE WHEN t.status = 'blocked' THEN t.id END) AS blocked
            FROM departments d
            LEFT JOIN tasks t ON t.department_id = d.id
            WHERE d.archived_at IS NULL
            GROUP BY d.id
            ORDER BY d.name ASC
            """
        ).fetchall()
        # last_chat_msg_time — отдельный запрос для каждого отдела (быстро на маленьких БД).
        result = []
        for r in rows:
            last_msg = conn.execute(
                "SELECT MAX(created_at) AS ts FROM chat_messages WHERE department_id = ?",
                (r["dept_id"],),
            ).fetchone()
            result.append({
                "dept_id":            r["dept_id"],
                "dept_name":          r["dept_name"],
                "wip":                r["wip"],
                "review":             r["review"],
                "blocked":            r["blocked"],
                "last_chat_msg_time": last_msg["ts"] if last_msg and last_msg["ts"] else None,
            })
        return result
    finally:
        conn.close()


# === Task Artifacts (Phase 2.0.1) ===

def _row_to_artifact(row: sqlite3.Row) -> dict[str, Any]:
    """Преобразовать строку task_artifacts в dict."""
    return {
        "id": row["id"],
        "task_id": row["task_id"],
        "file_path": row["file_path"],
        "kind": row["kind"],
        "created_at": row["created_at"],
    }


def insert_artifact(
    db_path: Path,
    task_id: str,
    file_path: str,
    kind: str,
    created_at: Optional[int] = None,
) -> dict[str, Any]:
    """Добавить артефакт к задаче.

    Args:
        task_id: id задачи
        file_path: путь к файлу (абсолютный или относительный)
        kind: тип артефакта ('log', 'result', 'screenshot', 'report', etc.)
        created_at: timestamp (по умолчанию текущее время)

    Returns:
        dict с данными артефакта, включая id
    """
    if created_at is None:
        created_at = int(time.time())

    conn = _connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO task_artifacts (task_id, file_path, kind, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (task_id, file_path, kind, created_at),
        )
        conn.commit()
        artifact_id = cursor.lastrowid

        row = conn.execute(
            "SELECT * FROM task_artifacts WHERE id = ?",
            (artifact_id,),
        ).fetchone()
        return _row_to_artifact(row)
    finally:
        conn.close()


def get_artifact(db_path: Path, artifact_id: int) -> Optional[dict[str, Any]]:
    """Получить артефакт по id."""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM task_artifacts WHERE id = ?",
            (artifact_id,),
        ).fetchone()
        return _row_to_artifact(row) if row else None
    finally:
        conn.close()


def list_artifacts(
    db_path: Path,
    task_id: str,
) -> list[dict[str, Any]]:
    """Получить все артефакты задачи, отсортированные по created_at DESC."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT * FROM task_artifacts
            WHERE task_id = ?
            ORDER BY created_at DESC
            """,
            (task_id,),
        ).fetchall()
        return [_row_to_artifact(row) for row in rows]
    finally:
        conn.close()


def update_artifact(
    db_path: Path,
    artifact_id: int,
    **fields: Any,
) -> Optional[dict[str, Any]]:
    """Обновить артефакт. Допустимые поля: kind, file_path."""
    allowed_fields = {"kind", "file_path"}
    fields = {k: v for k, v in fields.items() if k in allowed_fields}

    if not fields:
        return get_artifact(db_path, artifact_id)

    conn = _connect(db_path)
    try:
        placeholders = ", ".join(f"{k} = ?" for k in fields.keys())
        values = list(fields.values()) + [artifact_id]

        conn.execute(
            f"UPDATE task_artifacts SET {placeholders} WHERE id = ?",
            values,
        )
        conn.commit()

        return get_artifact(db_path, artifact_id)
    finally:
        conn.close()


def delete_artifact(db_path: Path, artifact_id: int) -> bool:
    """Удалить артефакт. Возвращает True если был удален."""
    conn = _connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM task_artifacts WHERE id = ?", (artifact_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


# === Projects ===
# Проекты — единица группировки задач для owner-а (один лендинг, одна
# кампания, один продукт). Папка артефактов: workspace/{code}-{slug}/.


def _row_to_project(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "code": row["code"],
        "slug": row["slug"],
        "title": row["title"],
        "status": row["status"],
        "created_at": row["created_at"],
        "archived_at": row["archived_at"],
    }


def create_project(db_path: Path, slug: str, title: str) -> dict[str, Any]:
    """Создать проект. Code (PRJ-NNN) генерируется автоинкрементом.

    Args:
        slug: техническое имя (латиница, дефисы), для папки workspace/.
        title: человекочитаемое название (любой язык).

    Returns dict со всеми полями проекта.

    Raises:
        ValueError: slug не валиден, либо slug/title пустые.
        sqlite3.IntegrityError: slug уже занят.
    """
    if not slug or not title:
        raise ValueError("slug и title обязательны")
    slug = slug.strip()
    if not all(c.isascii() and (c.isalnum() or c == "-") for c in slug):
        raise ValueError("slug должен содержать только латиницу, цифры и дефис")
    if slug.startswith("-") or slug.endswith("-"):
        raise ValueError("slug не может начинаться или заканчиваться дефисом")

    now = int(time.time())
    with write_lock(db_path):
        conn = _connect(db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            # Получаем следующий id заранее, чтобы сформировать code.
            row = conn.execute(
                "SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM projects"
            ).fetchone()
            next_id = int(row["next_id"])
            code = f"PRJ-{next_id:03d}"

            conn.execute(
                "INSERT INTO projects (id, code, slug, title, status, created_at) "
                "VALUES (?, ?, ?, ?, 'active', ?)",
                (next_id, code, slug, title.strip(), now),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (next_id,)).fetchone()
            return _row_to_project(row)
        finally:
            conn.close()


def list_projects(db_path: Path, include_archived: bool = False) -> list[dict[str, Any]]:
    """Список проектов, отсортированных по id ASC."""
    conn = _connect(db_path)
    try:
        if include_archived:
            cur = conn.execute("SELECT * FROM projects ORDER BY id ASC")
        else:
            cur = conn.execute(
                "SELECT * FROM projects WHERE status != 'archived' ORDER BY id ASC"
            )
        return [_row_to_project(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_project(db_path: Path, project_id_or_code: Any) -> Optional[dict[str, Any]]:
    """Получить проект по id (int) или code (строка вида 'PRJ-001')."""
    conn = _connect(db_path)
    try:
        if isinstance(project_id_or_code, int) or (
            isinstance(project_id_or_code, str) and project_id_or_code.isdigit()
        ):
            row = conn.execute(
                "SELECT * FROM projects WHERE id = ?", (int(project_id_or_code),)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM projects WHERE code = ? OR slug = ?",
                (project_id_or_code, project_id_or_code),
            ).fetchone()
        return _row_to_project(row) if row else None
    finally:
        conn.close()


def link_task_to_project(
    db_path: Path, task_id: str, project_id: Optional[int]
) -> Optional[dict[str, Any]]:
    """Привязать задачу к проекту (или отвязать, если project_id=None)."""
    with write_lock(db_path):
        conn = _connect(db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                "UPDATE tasks SET project_id = ?, updated_at = ? WHERE id = ?",
                (project_id, int(time.time()), task_id),
            )
            if cur.rowcount == 0:
                conn.execute("ROLLBACK")
                return None
            conn.execute("COMMIT")
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return _row_to_task(row) if row else None
        finally:
            conn.close()


# === App state (Task 99119C362B4A: persistence для auto_mode) ===


def get_app_state(db_path: Path, key: str, default: Optional[str] = None) -> Optional[str]:
    """Прочитать значение состояния приложения из БД.

    Args:
        db_path: путь к БД
        key: ключ состояния (напр. 'auto_mode')
        default: значение по умолчанию если key не найден

    Returns:
        значение из app_state, или default если не найдено
    """
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT value FROM app_state WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default
    finally:
        conn.close()


def set_app_state(db_path: Path, key: str, value: str) -> None:
    """Сохранить значение состояния приложения в БД.

    Args:
        db_path: путь к БД
        key: ключ состояния (напр. 'auto_mode')
        value: значение (строка)
    """
    now = int(time.time())
    with write_lock(db_path):
        conn = _connect(db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            # UPSERT: INSERT OR REPLACE
            conn.execute(
                "INSERT OR REPLACE INTO app_state (key, value, updated_at) VALUES (?, ?, ?)",
                (key, value, now),
            )
            conn.execute("COMMIT")
        finally:
            conn.close()

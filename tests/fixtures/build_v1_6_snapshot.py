#!/usr/bin/env python3
"""Сборщик anonymized snapshot БД pride-tasks схемы v1.x (до ADR-003).

Используется one-time или при изменении v1.x схемы:
    python tests/fixtures/build_v1_6_snapshot.py

Результат: `tests/fixtures/v1.6_snapshot.db` — sqlite-файл со схемой v1.x
(БЕЗ таблицы departments, БЕЗ колонок department_id) и небольшим
набором детерминированных синтетических данных.

Содержание snapshot'а:
- 7 default-ролей (как в v1.x init_db).
- 5 задач (todo / wip / review / done) с разными assignee.
- 3 task_comments.
- 4 chat_messages (от пользователя, тимлида, бэкенда, qa).
- 1 task_dependency (linear chain).
- 2 claude_sessions для покрытия таблицы.

ВАЖНО: никаких реальных данных пользователя — все синтетика.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

# v1.x SQLA schema — точная копия из git show f79e743^:mcp_server/pride_tasks/db.py
SCHEMA_V1_SQL = """
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
  FOREIGN KEY (parent_id) REFERENCES tasks(id)
);

CREATE INDEX IF NOT EXISTS idx_tasks_status   ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_assignee ON tasks(assignee);
CREATE INDEX IF NOT EXISTS idx_tasks_parent   ON tasks(parent_id);

CREATE TABLE IF NOT EXISTS task_comments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT NOT NULL,
  author TEXT NOT NULL,
  text TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  FOREIGN KEY (task_id) REFERENCES tasks(id)
);

CREATE INDEX IF NOT EXISTS idx_comments_task ON task_comments(task_id);

CREATE TABLE IF NOT EXISTS roles (
  name TEXT PRIMARY KEY,
  description TEXT NOT NULL,
  capabilities TEXT NOT NULL DEFAULT '[]'
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

CREATE INDEX IF NOT EXISTS idx_deps_task    ON task_dependencies(task_id);
CREATE INDEX IF NOT EXISTS idx_deps_blocker ON task_dependencies(depends_on);

CREATE TABLE IF NOT EXISTS chat_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  author TEXT NOT NULL,
  text TEXT NOT NULL,
  created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chat_created ON chat_messages(created_at);

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
"""

# Default v1.x roles (без HR, без department_id).
DEFAULT_ROLES_V1 = [
    ("тимлид", "Coordinator agent (v1.6 fixture).", ["декомпозиция", "ревью"]),
    ("бэкенд", "Python backend agent (v1.6 fixture).", ["python", "sqlite"]),
    ("qa", "QA agent (v1.6 fixture).", ["pytest", "smoke"]),
    ("архитектор", "Architect agent (v1.6 fixture).", ["adr", "design"]),
    ("frontend", "Frontend agent (v1.6 fixture).", ["js", "css"]),
    ("devops", "DevOps agent (v1.6 fixture).", ["docker", "ci"]),
    ("техписатель", "Tech writer agent (v1.6 fixture).", ["docs"]),
]

# Anonymized задачи (детерминированные id и фиксированный timestamp для воспроизводимости).
BASE_TS = 1750000000  # 2025-06-15 — фиксированный момент времени, не связан с реальными данными
TASKS = [
    ("t100sample01", "FIX-001: sample bug",            "Anonymized fixture task #1.",  "done",   "бэкенд", "пользователь", "P2", BASE_TS - 7200, BASE_TS - 3600, BASE_TS - 1800),
    ("t100sample02", "FEAT-002: sample feature",       "Anonymized fixture task #2.",  "review", "qa",      "тимлид",       "P1", BASE_TS - 6000, BASE_TS - 1200, None),
    ("t100sample03", "DOC-003: anonymized doc",        "Anonymized fixture task #3.",  "wip",    "техписатель", "тимлид",   "P2", BASE_TS - 4800, BASE_TS - 600,  None),
    ("t100sample04", "OPS-004: anonymized chore",      "Anonymized fixture task #4.",  "todo",   "devops",  "пользователь", "P3", BASE_TS - 3600, BASE_TS - 3600, None),
    ("t100sample05", "DESIGN-005: anonymized request", "Anonymized fixture task #5.",  "todo",   None,      "пользователь", "P2", BASE_TS - 1800, BASE_TS - 1800, None),
]

COMMENTS = [
    ("t100sample01", "бэкенд",        "Sample comment: исправлено.",              BASE_TS - 3500),
    ("t100sample01", "qa",            "Sample comment: проверено, тесты green.",  BASE_TS - 1900),
    ("t100sample02", "тимлид",        "Sample comment: на ревью.",                BASE_TS - 1200),
]

CHATS = [
    ("пользователь", "Sample chat msg 1 (fixture).", BASE_TS - 5400),
    ("тимлид",       "Sample chat msg 2 (fixture).", BASE_TS - 5300),
    ("бэкенд",       "Sample chat msg 3 (fixture).", BASE_TS - 3400),
    ("qa",           "Sample chat msg 4 (fixture).", BASE_TS - 1800),
]

DEPS = [
    # t100sample02 ждёт t100sample01.
    ("t100sample02", "t100sample01", BASE_TS - 5900),
]

SESSIONS = [
    (BASE_TS - 8000, BASE_TS - 7800, 200000, 5,  1500, 800,  0.012, "claude-opus-4-7", 0),
    (BASE_TS - 4000, BASE_TS - 3900, 100000, 3,  900,  400,  0.005, "claude-sonnet-4-5", 0),
]


def build(out_path: Path) -> None:
    """Создать sqlite-файл v1.x с anonymized данными по пути out_path."""
    if out_path.exists():
        out_path.unlink()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(out_path)
    try:
        conn.executescript(SCHEMA_V1_SQL)

        # Роли.
        for name, desc, caps in DEFAULT_ROLES_V1:
            conn.execute(
                "INSERT INTO roles (name, description, capabilities) VALUES (?, ?, ?)",
                (name, desc, json.dumps(caps, ensure_ascii=False)),
            )

        # Задачи.
        for (tid, title, descr, status, assignee, reporter, prio, created, updated, completed) in TASKS:
            conn.execute(
                "INSERT INTO tasks (id, title, description, status, assignee, reporter, priority, labels, "
                "parent_id, requires_approval, created_at, updated_at, due_at, completed_at, result) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, ?, ?, NULL, ?, NULL)",
                (tid, title, descr, status, assignee, reporter, prio, json.dumps(["fixture"]),
                 created, updated, completed),
            )

        # Комментарии.
        for (task_id, author, text, created) in COMMENTS:
            conn.execute(
                "INSERT INTO task_comments (task_id, author, text, created_at) VALUES (?, ?, ?, ?)",
                (task_id, author, text, created),
            )

        # Чат.
        for (author, text, created) in CHATS:
            conn.execute(
                "INSERT INTO chat_messages (author, text, created_at) VALUES (?, ?, ?)",
                (author, text, created),
            )

        # Зависимости.
        for (task_id, depends_on, created) in DEPS:
            conn.execute(
                "INSERT INTO task_dependencies (task_id, depends_on, created_at) VALUES (?, ?, ?)",
                (task_id, depends_on, created),
            )

        # Сессии.
        for s in SESSIONS:
            conn.execute(
                "INSERT INTO claude_sessions (started_at, finished_at, duration_ms, num_turns, "
                "input_tokens, output_tokens, total_cost_usd, model, is_error) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                s,
            )

        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    out = Path(__file__).resolve().parent / "v1.6_snapshot.db"
    build(out)
    print(f"Created v1.x snapshot at: {out}")

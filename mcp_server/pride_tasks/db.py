"""SQLite-слой канбана pride-tasks.

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
    """Путь к БД канбана. PRIDE_TASKS_DB переопределяет (для тестов)."""

    env = os.environ.get("PRIDE_TASKS_DB")
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

CREATE TABLE IF NOT EXISTS chat_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  author TEXT NOT NULL,            -- 'пользователь' | 'тимлид' | 'бэкенд' | 'qa' | 'system'
  text TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  department_id TEXT REFERENCES departments(id)
);

CREATE INDEX IF NOT EXISTS idx_chat_created ON chat_messages(created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_department    ON tasks(department_id);
CREATE INDEX IF NOT EXISTS idx_tasks_dept_status   ON tasks(department_id, status);
CREATE INDEX IF NOT EXISTS idx_chat_department     ON chat_messages(department_id);

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
) -> dict[str, Any]:
    """Вставка задачи. Возвращает dict как _row_to_task."""

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
                  department_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
) -> list[dict[str, Any]]:
    """Список задач с фильтрами. label — substring по JSON-массиву labels."""

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
        elif key == "requires_approval":
            sets.append("requires_approval = ?")
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


def post_chat_message(db_path: Path, author: str, text: str) -> dict[str, Any]:
    """Постит сообщение в общий чат (пользователь ↔ тимлид)."""
    _allowed = {
        "пользователь", "тимлид", "бэкенд", "qa",
        "архитектор", "frontend", "devops", "техписатель",
        "system",
    }
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
                "INSERT INTO chat_messages (author, text, created_at) VALUES (?, ?, ?)",
                (author, text.strip(), now),
            )
            mid = cur.lastrowid
            conn.execute("COMMIT")
            cur = conn.execute("SELECT * FROM chat_messages WHERE id = ?", (mid,))
            r = cur.fetchone()
            return {"id": r["id"], "author": r["author"], "text": r["text"], "created_at": r["created_at"]}
        finally:
            conn.close()


def list_chat_messages(db_path: Path, *, since: int = 0, limit: int = 100) -> list[dict[str, Any]]:
    """Лента чата. since — unix-ts, limit — максимум сообщений."""
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "SELECT * FROM chat_messages WHERE created_at >= ? ORDER BY id ASC LIMIT ?",
            (since, limit),
        )
        return [
            {"id": r["id"], "author": r["author"], "text": r["text"], "created_at": r["created_at"]}
            for r in cur.fetchall()
        ]
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
            elif key == "requires_approval":
                sets.append("requires_approval = ?")
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

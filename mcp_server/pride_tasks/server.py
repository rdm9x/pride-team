"""MCP-сервер pride-tasks — точка входа (stdio).

Запуск:
    python -m pride_tasks.server          # stdio для Claude Code
    или через .mcp.json в /D.AI/команда/

Переменные окружения:
    PRIDE_TASKS_DB — путь к SQLite (по умолчанию /D.AI/команда/data/tasks.db).
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from pride_tasks import alerts, db, tools  # noqa: E402

logging.basicConfig(
    level=os.environ.get("PRIDE_TASKS_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("pride_tasks.server")

DB_PATH = db.default_db_path()
db.init_db(DB_PATH)
log.info("pride-tasks БД: %s", DB_PATH)

# Подхватываем .env.local рядом с БД (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
_loaded = alerts.load_env_file(DB_PATH.parent / ".env.local")
if _loaded:
    log.info("загружено %d env-переменных из data/.env.local", _loaded)

mcp = FastMCP("pride-tasks")


@mcp.tool()
def list_tasks(
    status: Optional[str] = None,
    assignee: Optional[str] = None,
    label: Optional[str] = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Список задач канбана с фильтрами.

    Args:
        status: один из todo|wip|needs_approval|review|done|blocked.
        assignee: одна из ролей тимлид|бэкенд|qa|пользователь.
        label: substring по labels (JSON-массиву).
        limit: максимум задач (по умолчанию 50, отсортированы по created_at DESC).
    """
    return tools.list_tasks(status=status, assignee=assignee, label=label, limit=limit)


@mcp.tool()
def get_task(task_id: str) -> dict[str, Any]:
    """Прочитать задачу с историей комментов и списком подзадач.

    Args:
        task_id: id задачи (uuid-hex 12 символов).
    """
    return tools.get_task(task_id)


@mcp.tool()
def create_task(
    title: str,
    description: str = "",
    assignee: Optional[str] = None,
    reporter: Optional[str] = None,
    priority: str = "P2",
    parent_id: Optional[str] = None,
    requires_approval: bool = False,
    status: str = "todo",
    labels: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Создать задачу.

    Для approval-gate: status='needs_approval', requires_approval=True,
    labels=['approval', '<тип>'] (см. approval_gates.md).
    """
    return tools.create_task(
        title=title,
        description=description,
        assignee=assignee,
        reporter=reporter,
        priority=priority,
        parent_id=parent_id,
        requires_approval=requires_approval,
        status=status,
        labels=labels,
    )


@mcp.tool()
def update_task(
    task_id: str,
    status: Optional[str] = None,
    assignee: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    priority: Optional[str] = None,
    labels: Optional[list[str]] = None,
    requires_approval: Optional[bool] = None,
) -> dict[str, Any]:
    """Обновить поля задачи. Передавай только меняемые."""
    return tools.update_task(
        task_id,
        status=status,
        assignee=assignee,
        title=title,
        description=description,
        priority=priority,
        labels=labels,
        requires_approval=requires_approval,
    )


@mcp.tool()
def claim_task(task_id: str, assignee: str) -> dict[str, Any]:
    """Атомарно взять задачу в работу (assignee=null или совпадает).

    Защищено fcntl-lock + SQLite BEGIN IMMEDIATE. Возвращает 'конфликт'
    если задача уже у другой роли.
    """
    return tools.claim_task(task_id, assignee)


@mcp.tool()
def add_comment(task_id: str, author: str, text: str) -> dict[str, Any]:
    """Записать сообщение в историю задачи (видно в дашборде).

    Args:
        task_id: id задачи.
        author: одна из ролей.
        text: текст комментария.
    """
    return tools.add_comment(task_id, author, text)


@mcp.tool()
def submit_result(
    task_id: str,
    result: dict[str, Any],
    new_status: Optional[str] = None,
) -> dict[str, Any]:
    """Сохранить результат подзадачи. Опционально сменить статус.

    Используется бэкендом и QA при завершении работы. result свободной
    структуры — обычно {статус, файлы_изменены, тесты, summary}.
    """
    return tools.submit_result(task_id, result, new_status)


@mcp.tool()
def list_roles() -> dict[str, Any]:
    """Список ролей команды с их описанием и capabilities."""
    return tools.list_roles()


@mcp.tool()
def add_dependency(task_id: str, depends_on: str) -> dict[str, Any]:
    """Объявить что task_id блокируется задачей depends_on.

    Используй при декомпозиции: «B нельзя делать пока A не закрыта».
    Запрещены самозависимости и циклы.
    """
    return tools.add_dependency(task_id, depends_on)


@mcp.tool()
def remove_dependency(task_id: str, depends_on: str) -> dict[str, Any]:
    """Снять связь зависимости."""
    return tools.remove_dependency(task_id, depends_on)


@mcp.tool()
def get_dependencies(task_id: str) -> dict[str, Any]:
    """Что блокирует эту задачу (blocked_by) и что она блокирует (blocking).

    Используй при выборе следующей задачи: если blocked_by непуст и там
    есть незакрытые — не бери задачу в работу.
    """
    return tools.get_dependencies(task_id)


@mcp.tool()
def notify_dmitry(text: str, level: str = "info") -> dict[str, Any]:
    """Отправить короткое Telegram-уведомление Дмитрию.

    Используй сдержанно: при окончании длинной сессии с короткой сводкой,
    или когда что-то реально срочно. Не злоупотреблять.

    level: info | warn | error | ok.
    """
    return tools.notify_dmitry(text, level=level)


@mcp.tool()
def chat_recent(since: int = 0, limit: int = 50) -> dict[str, Any]:
    """Прочитать чат Дмитрия с командой.

    Используй при старте сессии тимлида (СРАЗУ после list_tasks):
    если есть новые сообщения от Дмитрия — ответь через chat_post.
    """
    return tools.chat_recent(since=since, limit=limit)


@mcp.tool()
def chat_post(author: str, text: str) -> dict[str, Any]:
    """Отправить сообщение в чат (author — твоя роль)."""
    return tools.chat_post(author, text)


def main() -> None:
    log.info("pride-tasks MCP-сервер стартует (stdio)")
    mcp.run()


if __name__ == "__main__":
    main()

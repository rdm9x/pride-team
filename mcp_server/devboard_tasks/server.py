"""MCP-сервер devboard-tasks — точка входа (stdio).

Запуск:
    python -m devboard_tasks.server          # stdio для Claude Code
    или через .mcp.json в корне devboard

Переменные окружения:
    DEVBOARD_TASKS_DB — путь к SQLite (по умолчанию devboard/data/tasks.db).
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

from devboard_tasks import alerts, db, tools  # noqa: E402

logging.basicConfig(
    level=os.environ.get("DEVBOARD_TASKS_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("devboard_tasks.server")

DB_PATH = db.default_db_path()
db.init_db(DB_PATH)
log.info("devboard-tasks БД: %s", DB_PATH)

# Подхватываем .env.local рядом с БД (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
_loaded = alerts.load_env_file(DB_PATH.parent / ".env.local")
if _loaded:
    log.info("загружено %d env-переменных из data/.env.local", _loaded)

mcp = FastMCP("devboard-tasks")


@mcp.tool()
def list_tasks(
    status: Optional[str] = None,
    assignee: Optional[str] = None,
    label: Optional[str] = None,
    limit: int = 50,
    department_id: Optional[str] = None,
) -> dict[str, Any]:
    """Список задач канбана с фильтрами.

    Args:
        status: один из todo|wip|needs_approval|review|done|blocked.
        assignee: одна из ролей тимлид|бэкенд|qa|пользователь.
        label: substring по labels (JSON-массиву).
        limit: максимум задач (по умолчанию 50, отсортированы по created_at DESC).
        department_id: фильтр по отделу. None (default) — все задачи.
    """
    return tools.list_tasks(status=status, assignee=assignee, label=label, limit=limit, department_id=department_id)


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
    department_id: str = "dev",
) -> dict[str, Any]:
    """Создать задачу.

    Для approval-gate: status='needs_approval', requires_approval=True,
    labels=['approval', '<тип>'] (см. approval_gates.md).

    department_id: отдел (по умолчанию 'dev').
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
        department_id=department_id,
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
def notify_user(text: str, level: str = "info") -> dict[str, Any]:
    """Отправить короткое Telegram-уведомление пользователю.

    Используй сдержанно: при окончании длинной сессии с короткой сводкой,
    или когда что-то реально срочно. Не злоупотреблять.

    level: info | warn | error | ok.
    """
    return tools.notify_user(text, level=level)


@mcp.tool()
def chat_recent(
    since: int = 0,
    limit: int = 50,
    department_id: Optional[str] = "dev",
) -> dict[str, Any]:
    """Прочитать чат пользователя с командой.

    Используй при старте сессии тимлида (СРАЗУ после list_tasks):
    если есть новые сообщения от пользователя — ответь через chat_post.

    department_id='dev' (default) — канал отдела. None — глобальный канал.
    """
    return tools.chat_recent(since=since, limit=limit, department_id=department_id)


@mcp.tool()
def chat_post(
    author: str,
    text: str,
    department_id: Optional[str] = "dev",
) -> dict[str, Any]:
    """Отправить сообщение в чат (author — твоя роль).

    department_id='dev' (default) — в канал отдела. None — в глобальный канал.
    """
    return tools.chat_post(author, text, department_id=department_id)


@mcp.tool()
def parse_task_description(task_id: str) -> dict[str, Any]:
    """Распарсить description задачи на структурированные части (TL;DR, шаги, acceptance).

    Используется фронтенду для красивого отображения задач в user-mode.
    Возвращает структурированный JSON с частями + исходный markdown для agent-mode.
    """
    return tools.parse_task_description(task_id)


@mcp.tool()
def register_task_artifact(
    task_id: str,
    file_path: str,
    kind: str = "artifact",
) -> dict[str, Any]:
    """Зарегистрировать артефакт (файл) связанный с задачей.

    Args:
        task_id: id задачи (uuid-hex 12 символов). Задача должна быть привязана
            к проекту (link_task_to_project), иначе путь некуда нормализовать.
        file_path: относительный путь внутри workspace/. Допустимо передать
            только имя файла (например 'copy.md') — функция сама пристроит
            путь по схеме workspace/<code>-<slug>/<dept>/<task_id>/<file>.
        kind: тип артефакта ('artifact' по умолчанию, либо 'log', 'report', ...).

    Returns:
        {status, artifact_id, task_id, file_path, kind, created_at}
    """
    return tools.register_task_artifact(task_id=task_id, file_path=file_path, kind=kind)


# === Projects ===
# Управляющий создаёт проект когда owner просит «новый проект Х», затем
# привязывает связанные задачи через link_task_to_project. Артефакты
# автоматически складываются в workspace/<code>-<slug>/<отдел>/<id-задачи>/.


@mcp.tool()
def create_project(slug: str, title: str) -> dict[str, Any]:
    """Создать новый проект.

    Args:
        slug: техническое имя на латинице (a-z, 0-9, дефис) для пути workspace/.
            Пример: 'landing-outdoor'.
        title: человекочитаемое название (любой язык).
            Пример: 'Лендинг outdoor billboards'.

    Returns:
        {status, project: {id, code (PRJ-NNN), slug, title, status, created_at}}.

    После создания папка workspace/<code>-<slug>/ готова принимать артефакты
    задач, привязанных к проекту.
    """
    return tools.create_project(slug=slug, title=title)


@mcp.tool()
def list_projects(include_archived: bool = False) -> dict[str, Any]:
    """Список проектов (по умолчанию без архивированных)."""
    return tools.list_projects(include_archived=include_archived)


@mcp.tool()
def get_project(project_id_or_code: str) -> dict[str, Any]:
    """Получить детали проекта по id (число), code ('PRJ-001') или slug."""
    return tools.get_project(project_id_or_code=project_id_or_code)


@mcp.tool()
def link_task_to_project(
    task_id: str,
    project_id_or_code: Optional[str] = None,
) -> dict[str, Any]:
    """Привязать задачу к проекту (или отвязать, если project_id_or_code пуст).

    project_id_or_code принимает int id, code 'PRJ-001' или slug.
    """
    return tools.link_task_to_project(
        task_id=task_id, project_id_or_code=project_id_or_code
    )


@mcp.tool()
def archive_project(project_id_or_code: str) -> dict[str, Any]:
    """Архивировать проект (status='archived'). Папка workspace/ не удаляется."""
    return tools.archive_project(project_id_or_code=project_id_or_code)


@mcp.tool()
def list_departments() -> dict[str, Any]:
    """Список активных отделов с количеством открытых и общих задач."""
    return tools.list_departments()


@mcp.tool()
def get_department(department_id: str) -> dict[str, Any]:
    """Детали одного отдела + список его ролей.

    Args:
        department_id: id отдела (например 'dev', 'marketing').
    """
    return tools.get_department(department_id)


@mcp.tool()
def create_department(
    name: str,
    description: str = "",
    template_id: Optional[str] = None,
    icon: str = "🗂",
) -> dict[str, Any]:
    """Создать новый отдел. id генерируется автоматически как slug из name.

    Args:
        name: название отдела (уникальное).
        description: описание (опционально).
        template_id: ссылка на шаблон (опционально).
        icon: иконка (по умолчанию 🗂).
    """
    return tools.create_department(name, description=description, template_id=template_id, icon=icon)


# === Manager Memory (B2, ADR-007 §2.2) — только для роли managing-director ===
#
# Каждый MCP-tool принимает явный `caller_role`, который должен быть
# 'managing-director'. Иначе возвращается status=forbidden. Это намеренный
# дизайн: MCP-протокол сам не несёт identity, поэтому identity передаётся
# параметром (точно как user_id у других tools).


@mcp.tool()
def manager_memory_add(
    text: str,
    source: str,
    path: Optional[str] = None,
    tags: Optional[list[str]] = None,
    caller_role: Optional[str] = None,
) -> dict[str, Any]:
    """Сохранить чанк в долгосрочную память Управляющего.

    ДОСТУП: только роль 'managing-director'. Иначе — forbidden.

    Args:
        text: что запомнить.
        source: 'conversation' | 'note' | 'recall' | 'planning' | 'import'.
        path: ссылка на исходник (chat#1234, adr/0009, planning_session#abc).
        tags: массив тегов для фасетной фильтрации.
        caller_role: ОБЯЗАТЕЛЬНО передавать 'managing-director'.
    """
    return tools.manager_memory_add(
        text=text, source=source, path=path, tags=tags, caller_role=caller_role
    )


@mcp.tool()
def manager_memory_search(
    query: str,
    source: Optional[str] = None,
    limit: int = 10,
    caller_role: Optional[str] = None,
) -> dict[str, Any]:
    """FTS5-поиск по памяти Управляющего. Возвращает результаты со score.

    ДОСТУП: только роль 'managing-director'. Иначе — forbidden.

    Score = bm25(manager_fts): меньше = релевантнее. Архивные чанки исключены.
    """
    return tools.manager_memory_search(
        query=query, source=source, limit=limit, caller_role=caller_role
    )


@mcp.tool()
def manager_memory_get(
    chunk_id: int,
    caller_role: Optional[str] = None,
) -> dict[str, Any]:
    """Прочитать один чанк по id.

    ДОСТУП: только роль 'managing-director'.
    """
    return tools.manager_memory_get(chunk_id=chunk_id, caller_role=caller_role)


@mcp.tool()
def manager_memory_recent(
    source: Optional[str] = None,
    limit: int = 20,
    caller_role: Optional[str] = None,
) -> dict[str, Any]:
    """Последние N не-архивных чанков (updated_at DESC). Bootstrap-режим.

    ДОСТУП: только роль 'managing-director'.
    """
    return tools.manager_memory_recent(
        source=source, limit=limit, caller_role=caller_role
    )


@mcp.tool()
def manager_memory_archive(
    chunk_id: int,
    caller_role: Optional[str] = None,
) -> dict[str, Any]:
    """Soft-delete чанка (archived_at = now).

    ДОСТУП: только роль 'managing-director'.
    """
    return tools.manager_memory_archive(chunk_id=chunk_id, caller_role=caller_role)


# === Planning sessions (B3, ADR-009 §2.4 + §2.6) ===
#
# 4 tool'а для координации планёрок Управляющим. caller_role обязателен —
# должен быть 'managing-director'. Иначе 403 forbidden.


@mcp.tool()
def list_all_inboxes(caller_role: Optional[str] = None) -> dict[str, Any]:
    """Агрегат по всем активным отделам для Управляющего (ADR-009 §2.6).

    Возвращает для каждого отдела: dept_id, dept_name, wip/review/blocked
    counts, last_chat_msg_time. Архивированные отделы исключены.

    ДОСТУП: только роль 'managing-director'.
    """
    return tools.list_all_inboxes(caller_role=caller_role)


@mcp.tool()
def start_planning_session(
    owner_request: str,
    departments: list[str],
    caller_role: Optional[str] = None,
) -> dict[str, Any]:
    """Phase 1 (gathering): создать planning_session и позвать лидов отделов в чат.

    Создаёт запись в planning_sessions(phase='gathering'). Для каждого dept_id
    в `departments` постит chat_post(author='managing-director') с текстом-приглашением.

    ДОСТУП: только роль 'managing-director'.

    Args:
        owner_request: исходное сообщение owner'а (требование, контекст).
        departments: список dept_id отделов чьи лиды зовутся.
    """
    return tools.start_planning_session(
        owner_request, departments, caller_role=caller_role
    )


@mcp.tool()
def collect_planning_responses(
    planning_session_id: str,
    caller_role: Optional[str] = None,
) -> dict[str, Any]:
    """Phase 2 (discussion): собирает реплики лидов из чатов отделов в discussion_log.

    Читает chat_recent каждого участвующего отдела с момента started_at,
    исключает сообщения самого Управляющего, сортирует хронологически и
    сохраняет в planning_sessions.discussion_log. phase → 'discussion'.

    ДОСТУП: только роль 'managing-director'.
    """
    return tools.collect_planning_responses(
        planning_session_id, caller_role=caller_role
    )


@mcp.tool()
def finalize_planning_session(
    planning_session_id: str,
    owner_answer: str,
    caller_role: Optional[str] = None,
) -> dict[str, Any]:
    """Phase 4 (distribution): парсит owner_answer на N задач и создаёт cross-task в каждый отдел.

    owner_answer может содержать заголовки секций вида '<dept>:', '<dept> -'
    или '<dept> —' — каждая секция = одна задача в соответствующий отдел.
    Без заголовков → одна общая задача каждому отделу.

    Задачи создаются с requester_role_slug='managing-director' (без
    requester_department_id — Управляющий глобальная роль). phase → 'done'.

    ДОСТУП: только роль 'managing-director'.
    """
    return tools.finalize_planning_session(
        planning_session_id, owner_answer, caller_role=caller_role
    )


def main() -> None:
    log.info("devboard-tasks MCP-сервер стартует (stdio)")
    mcp.run()


if __name__ == "__main__":
    main()

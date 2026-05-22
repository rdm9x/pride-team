"""8 функций-инструментов канбана. Используются:
  - Через MCP-протокол из сессии тимлида/subagent'ов (Claude Code).
  - Напрямую из Flask-дашборда (через прямой import).

Контракт каждой функции — dict-in/dict-out, status в результате.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path
from typing import Any, Optional

from pride_tasks import db, parser
from pride_tasks.models import DEFAULT_DEPARTMENT_ID, PRIORITIES, ROLES, STATUSES

logger = logging.getLogger(__name__)


def _safety_net_done(task_id: str, title: str, db_path: Path) -> None:
    """Вставляет системный комментарий и постит алерт в чат.

    Вызывается когда safety-net перехватывает попытку выставить status=done
    через MCP (update_task или submit_result). Не кидает исключений.
    """
    short_id = task_id[:8]
    comment_text = (
        f"⚠️ Safety-net: попытка выставить status=done через MCP перехвачена. "
        f"Задача переведена в review для owner-acceptance."
    )
    chat_text = (
        f"⚠️ Safety-net: тимлид пытался поставить status=done для #{short_id} \"{title}\". "
        f"Переведено в review для owner-acceptance."
    )
    logger.warning("safety-net triggered: attempt to set done via MCP for task %s (%r)", task_id, title)
    try:
        db.insert_system_comment(db_path, task_id, comment_text)
    except Exception as exc:  # noqa: BLE001
        logger.error("safety-net: failed to insert system comment for %s: %s", task_id, exc)
    try:
        db.post_chat_message(db_path, "system", chat_text)
    except Exception as exc:  # noqa: BLE001
        logger.error("safety-net: failed to post chat message for %s: %s", task_id, exc)


def _resolve_db_path(db_path: Optional[Path] = None) -> Path:
    return Path(db_path) if db_path else db.default_db_path()


# === 1. list_tasks ===


def list_tasks(
    status: Optional[str] = None,
    assignee: Optional[str] = None,
    label: Optional[str] = None,
    limit: int = 50,
    department_id: Optional[str] = None,
    *,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Список задач канбана с фильтрами.

    department_id=None — возвращает ВСЕ задачи (глобальный view).
    department_id='dev' — только задачи отдела dev.
    """

    if status is not None and status not in STATUSES:
        return {"статус": "error", "status": "error", "причина": f"неизвестный status: {status}", "reason": f"неизвестный status: {status}"}
    path = _resolve_db_path(db_path)
    # _filter_department=True только если department_id явно передан (не None)
    _filter = department_id is not None
    tasks = db.list_tasks(
        path,
        status=status,
        assignee=assignee,
        label=label,
        limit=limit,
        department_id=department_id,
        _filter_department=_filter,
    )
    return {"статус": "ok", "всего": len(tasks), "задачи": tasks}


# === 2. get_task ===


def get_task(task_id: str, *, db_path: Optional[Path] = None) -> dict[str, Any]:
    """Прочитать задачу с историей комментов и подзадачами."""

    if not task_id:
        return {"статус": "error", "status": "error", "причина": "task_id пустой", "reason": "task_id пустой"}
    path = _resolve_db_path(db_path)
    task = db.get_task(path, task_id, with_history=True)
    if task is None:
        return {"статус": "not_found", "task_id": task_id}
    return {"статус": "ok", "задача": task}


# === 3. create_task ===


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
    department_id: str = DEFAULT_DEPARTMENT_ID,
    *,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Создать задачу. Минимум — title.

    department_id по умолчанию 'dev' (backward compatible).
    """

    if not title or not title.strip():
        return {"статус": "error", "status": "error", "причина": "title пустой", "reason": "title пустой"}
    if status not in STATUSES:
        return {"статус": "error", "status": "error", "причина": f"неизвестный status: {status}", "reason": f"неизвестный status: {status}"}
    if priority not in PRIORITIES:
        return {"статус": "error", "status": "error", "причина": f"неизвестный priority: {priority}", "reason": f"неизвестный priority: {priority}"}
    if assignee is not None and assignee not in ROLES:
        return {"статус": "error", "status": "error", "причина": f"неизвестная роль assignee: {assignee}", "reason": f"неизвестная роль assignee: {assignee}"}
    path = _resolve_db_path(db_path)
    if parent_id and db.get_task(path, parent_id) is None:
        return {"статус": "error", "status": "error", "причина": f"parent_id {parent_id} не существует", "reason": f"parent_id {parent_id} не существует"}
    task = db.insert_task(
        path,
        title=title.strip(),
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
    return {"статус": "ok", "задача": task}


# === 4. update_task ===


def update_task(
    task_id: str,
    *,
    status: Optional[str] = None,
    assignee: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    priority: Optional[str] = None,
    labels: Optional[list[str]] = None,
    requires_approval: Optional[bool] = None,
    db_path: Optional[Path] = None,
    _bypass_safety_net: bool = False,
) -> dict[str, Any]:
    """Обновить поля задачи. Передавай только то, что меняется.

    _bypass_safety_net=True используется Flask-дашбордом для UI-операций
    (approve, reject, прямой PATCH от пользователя) — они разрешены ставить done.
    MCP-вызовы не передают этот аргумент (default=False) → safety-net активен.
    """

    if not task_id:
        return {"статус": "error", "status": "error", "причина": "task_id пустой", "reason": "task_id пустой"}
    if status is not None and status not in STATUSES:
        return {"статус": "error", "status": "error", "причина": f"неизвестный status: {status}", "reason": f"неизвестный status: {status}"}
    if priority is not None and priority not in PRIORITIES:
        return {"статус": "error", "status": "error", "причина": f"неизвестный priority: {priority}", "reason": f"неизвестный priority: {priority}"}
    if assignee is not None and assignee not in ROLES:
        return {"статус": "error", "status": "error", "причина": f"неизвестная роль assignee: {assignee}", "reason": f"неизвестная роль assignee: {assignee}"}

    # --- Safety-net: MCP не может напрямую выставить done ---
    # Если статус переводится в done через MCP-инструмент — переключаем на review
    # и уведомляем через системный комментарий + чат-алерт.
    # Исключение: _bypass_safety_net=True (вызов из UI) или задача уже в done.
    if status == "done" and not _bypass_safety_net:
        path = _resolve_db_path(db_path)
        existing = db.get_task(path, task_id)
        if existing is None:
            return {"статус": "not_found", "task_id": task_id}
        if existing.get("status") != "done":
            status = "review"
            _safety_net_done(task_id, existing.get("title", ""), path)

    fields: dict[str, Any] = {}
    if status is not None:
        fields["status"] = status
    if assignee is not None:
        fields["assignee"] = assignee
    if title is not None:
        fields["title"] = title
    if description is not None:
        fields["description"] = description
    if priority is not None:
        fields["priority"] = priority
    if labels is not None:
        fields["labels"] = labels
    if requires_approval is not None:
        fields["requires_approval"] = requires_approval
    path = _resolve_db_path(db_path)
    updated = db.update_task(path, task_id, **fields)
    if updated is None:
        return {"статус": "not_found", "task_id": task_id}
    return {"статус": "ok", "задача": updated}


# === 5. claim_task ===


def claim_task(
    task_id: str,
    assignee: str,
    *,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Атомарно взять задачу в работу. Защищено fcntl + BEGIN IMMEDIATE."""

    if not task_id:
        return {"статус": "error", "status": "error", "причина": "task_id пустой", "reason": "task_id пустой"}
    if assignee not in ROLES:
        return {"статус": "error", "status": "error", "причина": f"неизвестная роль: {assignee}", "reason": f"неизвестная роль: {assignee}"}
    path = _resolve_db_path(db_path)
    result = db.claim_task(path, task_id, assignee)
    if not result["ok"]:
        return {
            "статус": "конфликт" if result["reason"] == "conflict" else "not_found",
            "task_id": task_id,
            "причина": result.get("reason"),
            "reason": result.get("reason"),
            "текущий_assignee": result.get("current_assignee"),
        }
    return {"статус": "ok", "задача": result["task"]}


# === 6. add_comment ===


def add_comment(
    task_id: str,
    author: str,
    text: str,
    *,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Добавить запись в историю задачи."""

    if not task_id:
        return {"статус": "error", "status": "error", "причина": "task_id пустой", "reason": "task_id пустой"}
    if author not in ROLES:
        return {"статус": "error", "status": "error", "причина": f"неизвестный author: {author}", "reason": f"неизвестный author: {author}"}
    if not text or not text.strip():
        return {"статус": "error", "status": "error", "причина": "text пустой", "reason": "text пустой"}
    path = _resolve_db_path(db_path)
    try:
        comment = db.add_comment(path, task_id, author, text.strip())
    except KeyError:
        return {"статус": "not_found", "task_id": task_id}
    return {"статус": "ok", "комментарий": comment}


# === 7. submit_result ===


def submit_result(
    task_id: str,
    result: dict[str, Any],
    new_status: Optional[str] = None,
    *,
    db_path: Optional[Path] = None,
    _bypass_safety_net: bool = False,
) -> dict[str, Any]:
    """Закрыть подзадачу: сохранить результат и сменить статус.

    _bypass_safety_net=True используется Flask-дашбордом — UI-операции
    разрешены ставить done напрямую. MCP-вызовы не передают этот аргумент
    (default=False) → safety-net активен.
    """

    if not task_id:
        return {"статус": "error", "status": "error", "причина": "task_id пустой", "reason": "task_id пустой"}
    if not isinstance(result, dict):
        return {"статус": "error", "status": "error", "причина": "result должен быть dict", "reason": "result должен быть dict"}
    if new_status is not None and new_status not in STATUSES:
        return {"статус": "error", "status": "error", "причина": f"неизвестный new_status: {new_status}", "reason": f"неизвестный new_status: {new_status}"}

    # --- Safety-net: MCP не может напрямую выставить done ---
    # Если new_status == "done" — переключаем на review и уведомляем.
    # Исключение: _bypass_safety_net=True (вызов из UI) или задача уже в done.
    if new_status == "done" and not _bypass_safety_net:
        path = _resolve_db_path(db_path)
        existing = db.get_task(path, task_id)
        if existing is None:
            return {"статус": "not_found", "task_id": task_id}
        if existing.get("status") != "done":
            new_status = "review"
            _safety_net_done(task_id, existing.get("title", ""), path)

    path = _resolve_db_path(db_path)
    updated = db.submit_result(path, task_id, result, new_status)
    if updated is None:
        return {"статус": "not_found", "task_id": task_id}
    return {"статус": "ok", "задача": updated}


# === 8. list_roles ===


def add_dependency(
    task_id: str,
    depends_on: str,
    *,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Объявить что задача task_id ждёт закрытия depends_on.

    Используй когда декомпозируешь большую задачу на этапы (A → B → C),
    чтобы не пытаться делать B пока A не сделана.
    """
    if not task_id or not depends_on:
        return {"статус": "error", "status": "error", "причина": "task_id и depends_on обязательны", "reason": "task_id и depends_on обязательны"}
    path = _resolve_db_path(db_path)
    res = db.add_dependency(path, task_id, depends_on)
    if not res["ok"]:
        _reason = res.get("reason", "неизвестно")
        return {"статус": "error", "status": "error", "причина": _reason, "reason": _reason}
    return {"статус": "ok"}


def remove_dependency(
    task_id: str,
    depends_on: str,
    *,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Удалить связь зависимости."""
    path = _resolve_db_path(db_path)
    ok = db.remove_dependency(path, task_id, depends_on)
    return {"статус": "ok" if ok else "not_found"}


def get_dependencies(
    task_id: str,
    *,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Что блокирует эту задачу и что она блокирует."""
    if not task_id:
        return {"статус": "error", "status": "error", "причина": "task_id пустой", "reason": "task_id пустой"}
    path = _resolve_db_path(db_path)
    return {
        "статус": "ok",
        "blocked_by": db.get_blockers(path, task_id),
        "blocking": db.get_blocking(path, task_id),
    }


def notify_user(
    text: str,
    level: str = "info",
    *,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Отправить Telegram-уведомление пользователю.

    Используй когда:
      - закончил длинную сессию и пользователь должен прийти посмотреть результаты;
      - набралось несколько NEEDS APPROVAL подряд;
      - найдена критичная ошибка которая требует немедленного внимания.

    Не злоупотреблять — пользователь не хочет 30 нотификаций в час. По умолчанию
    одна короткая сводка в конце сессии хватает.

    Args:
        text: тело сообщения (plain text, без markdown).
        level: info / warn / error / ok — управляет emoji-префиксом.
    """
    from pride_tasks import alerts

    alerter = alerts.from_env()
    if alerter is None:
        return {"статус": "skip", "причина": "TELEGRAM_BOT_TOKEN/CHAT_ID не настроены", "reason": "TELEGRAM_BOT_TOKEN/CHAT_ID не настроены"}
    if not text or not text.strip():
        return {"статус": "error", "status": "error", "причина": "text пустой", "reason": "text пустой"}
    try:
        alerter.send(text.strip(), level=level)
    except alerts.TelegramAlertError as exc:
        return {"статус": "error", "status": "error", "причина": str(exc), "reason": str(exc)}
    return {"статус": "ok"}


def chat_recent(
    since: int = 0,
    limit: int = 50,
    department_id: Optional[str] = DEFAULT_DEPARTMENT_ID,
    *,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Прочитать последние сообщения чата.

    department_id='dev' (default) — канал отдела dev.
    department_id=None — глобальный межотдельный канал (department_id IS NULL).
    """
    path = _resolve_db_path(db_path)
    msgs = db.list_chat_messages(path, since=since, limit=limit, department_id=department_id)
    return {"статус": "ok", "всего": len(msgs), "сообщения": msgs}


def chat_post(
    author: str,
    text: str,
    department_id: Optional[str] = DEFAULT_DEPARTMENT_ID,
    *,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Отправить сообщение в чат. author — роль отправителя.

    department_id='dev' (default) — в канал отдела dev.
    department_id=None — в глобальный канал.
    """
    path = _resolve_db_path(db_path)
    try:
        msg = db.post_chat_message(path, author, text, department_id=department_id)
    except ValueError as exc:
        return {"статус": "error", "status": "error", "причина": str(exc), "reason": str(exc)}
    return {"статус": "ok", "сообщение": msg}


def list_roles(*, db_path: Optional[Path] = None) -> dict[str, Any]:
    """Список доступных ролей с их capabilities."""

    path = _resolve_db_path(db_path)
    roles = db.list_roles(path)
    return {"статус": "ok", "всего": len(roles), "роли": roles}


# === 9. list_departments / get_department / create_department ===


def _name_to_slug(name: str) -> str:
    """Генерирует slug из имени: lowercase ASCII, пробелы → дефисы."""
    # Убираем акценты / кириллицу транслитом через unicodedata (лучшее что есть без зависимостей)
    normalized = unicodedata.normalize("NFKD", name)
    ascii_str = normalized.encode("ascii", "ignore").decode("ascii")
    slug = ascii_str.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "dept"


def list_departments(*, db_path: Optional[Path] = None) -> dict[str, Any]:
    """Список активных отделов с counts (tasks_open, tasks_total)."""
    path = _resolve_db_path(db_path)
    departments = db.list_departments(path)
    return {"статус": "ok", "всего": len(departments), "отделы": departments}


def get_department(department_id: str, *, db_path: Optional[Path] = None) -> dict[str, Any]:
    """Детали одного отдела + список ролей.

    Args:
        department_id: id отдела (например 'dev', 'marketing').
    """
    if not department_id:
        return {"статус": "error", "status": "error", "причина": "department_id пустой", "reason": "department_id пустой"}
    path = _resolve_db_path(db_path)
    dept = db.get_department(path, department_id)
    if dept is None:
        return {"статус": "not_found", "department_id": department_id}
    return {"статус": "ok", "отдел": dept}


def create_department(
    name: str,
    description: str = "",
    template_id: Optional[str] = None,
    icon: str = "🗂",
    *,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Создать новый отдел. id генерируется как slug из name (lowercase ASCII, пробелы→дефисы).

    Args:
        name: название отдела (уникальное).
        description: описание (опционально).
        template_id: ссылка на шаблон (опционально).
        icon: иконка (по умолчанию 🗂).
    """
    if not name or not name.strip():
        return {"статус": "error", "status": "error", "причина": "name пустой", "reason": "name пустой"}
    dept_id = _name_to_slug(name.strip())
    if not dept_id:
        return {"статус": "error", "status": "error", "причина": "не удалось сгенерировать id из name", "reason": "не удалось сгенерировать id из name"}
    path = _resolve_db_path(db_path)
    try:
        dept = db.create_department(
            path,
            dept_id=dept_id,
            name=name.strip(),
            description=description,
            template_id=template_id,
            icon=icon,
        )
    except ValueError as exc:
        return {"статус": "error", "status": "error", "причина": str(exc), "reason": str(exc)}
    return {"статус": "ok", "отдел": dept}


# === 10. parse_task_description ===


def parse_task_description(task_id: str, *, db_path: Optional[Path] = None) -> dict[str, Any]:
    """Распарсить description задачи на структурированные части.

    Извлекает:
    - TL;DR (одна строка)
    - Шаги (## Что делать, ## Steps, и т.д.)
    - Acceptance criteria (## Acceptance, ## Acceptance Criteria и т.д.)
    - Варианты ответов (для кнопок)
    - Исходный markdown (для agent-mode)

    Используется фронтенду для user-friendly отображения задач.
    """
    if not task_id:
        return {"статус": "error", "status": "error", "причина": "task_id пустой", "reason": "task_id пустой"}

    path = _resolve_db_path(db_path)
    task = db.get_task(path, task_id)
    if task is None:
        return {"статус": "not_found", "task_id": task_id}

    description = task.get("description", "")
    parsed = parser.parse_task_description(description)

    return {
        "статус": "ok",
        "parsed": parsed.to_dict(),
    }

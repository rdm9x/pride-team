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
    model_hint: Optional[str] = None,
    *,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Создать задачу. Минимум — title.

    department_id по умолчанию 'dev' (backward compatible).
    model_hint — опциональный hint для роутера: 'opus', 'sonnet' или 'haiku'.
    Если задан — роутер может использовать этот hint при выборе модели (ADR-006).
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
        model_hint=model_hint,
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
    model_hint: Optional[str] = None,
    db_path: Optional[Path] = None,
    _bypass_safety_net: bool = False,
) -> dict[str, Any]:
    """Обновить поля задачи. Передавай только то, что меняется.

    _bypass_safety_net=True используется Flask-дашбордом для UI-операций
    (approve, reject, прямой PATCH от пользователя) — они разрешены ставить done.
    MCP-вызовы не передают этот аргумент (default=False) → safety-net активен.
    model_hint — опциональный hint для роутера: 'opus', 'sonnet' или 'haiku' (ADR-006).
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
    # Исключения:
    #   1. _bypass_safety_net=True (вызов из UI)
    #   2. Задача уже в done.
    #   3. Задача имеет label `night-auto` — explicit grant для night auto-mode batches.
    if status == "done" and not _bypass_safety_net:
        path = _resolve_db_path(db_path)
        existing = db.get_task(path, task_id)
        if existing is None:
            return {"статус": "not_found", "task_id": task_id}
        existing_labels = existing.get("labels") or []
        if "night-auto" in existing_labels:
            # Explicit grant — пропускаем safety-net.
            pass
        elif existing.get("status") != "done":
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
    if model_hint is not None:
        fields["model_hint"] = model_hint
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
    # Исключения: _bypass_safety_net=True, задача уже done, или label `night-auto`.
    if new_status == "done" and not _bypass_safety_net:
        path = _resolve_db_path(db_path)
        existing = db.get_task(path, task_id)
        if existing is None:
            return {"статус": "not_found", "task_id": task_id}
        existing_labels = existing.get("labels") or []
        if "night-auto" in existing_labels:
            pass
        elif existing.get("status") != "done":
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
    limit: int = 10,
    department_id: Optional[str] = DEFAULT_DEPARTMENT_ID,
    *,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Прочитать последние сообщения чата.

    department_id='dev' (default) — канал отдела dev.
    department_id=None — глобальный межотдельный канал (department_id IS NULL).

    ADR-006 (S15.2): default limit снижен с 50 до 10 для экономии токенов.
    При необходимости передавай limit явно (например limit=20).
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


# === 11. manager_memory_* (B2, ADR-007 §2.2) ===
#
# Долгосрочная память Управляющего. Доступно только роли `managing-director`
# (role gate на этом слое — БД остаётся «глупой» и хранит чанки без
# проверки кто читает).
#
# Стиль ошибок: {"статус": "forbidden", "status": "forbidden", "причина": "...",
# "reason": "..."} — повторяет паттерн остальных tools (двуязычные ключи).
# Семантически 403 forbidden передаётся через "статус": "forbidden".

_MANAGER_MEMORY_ROLE = "managing-director"
_MANAGER_VALID_SOURCES_TOOLS: tuple[str, ...] = (
    "conversation",
    "note",
    "recall",
    "planning",
    "import",
)


def _role_forbidden(caller_role: Optional[str]) -> dict[str, Any]:
    """Стандартный 403-ответ для нарушения role gate."""
    reason = (
        f"требуется роль {_MANAGER_MEMORY_ROLE!r}; получено: {caller_role!r}"
    )
    return {
        "статус": "forbidden",
        "status": "forbidden",
        "причина": reason,
        "reason": reason,
    }


def _check_manager_memory_role(caller_role: Optional[str]) -> Optional[dict[str, Any]]:
    """Возвращает 403-dict если caller не managing-director, иначе None."""
    if caller_role != _MANAGER_MEMORY_ROLE:
        return _role_forbidden(caller_role)
    return None


def manager_memory_add(
    text: str,
    source: str,
    path: Optional[str] = None,
    tags: Optional[list[str]] = None,
    *,
    caller_role: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Сохранить чанк в долгосрочную память Управляющего.

    Args:
        text: текст для запоминания (обязательно, не пустой).
        source: 'conversation' | 'note' | 'recall' | 'planning' | 'import'.
        path: опциональная ссылка на исходник (chat#1234, adr/0009, ...).
        tags: JSON-массив тегов для фасетов.
        caller_role: роль вызывающего; должна быть 'managing-director'.

    Возвращает:
        {"статус": "ok", "id": <int>, "чанк": {...}} при успехе.
        {"статус": "forbidden", ...} если caller_role != managing-director.
        {"статус": "error", ...} при невалидных параметрах.
    """
    deny = _check_manager_memory_role(caller_role)
    if deny is not None:
        return deny
    if not text or not text.strip():
        return {"статус": "error", "status": "error", "причина": "text пустой", "reason": "text пустой"}
    if source not in _MANAGER_VALID_SOURCES_TOOLS:
        reason = f"неизвестный source: {source!r} (ожидается один из {_MANAGER_VALID_SOURCES_TOOLS})"
        return {"статус": "error", "status": "error", "причина": reason, "reason": reason}
    if tags is not None and not isinstance(tags, list):
        return {"статус": "error", "status": "error", "причина": "tags должен быть list[str]", "reason": "tags должен быть list[str]"}

    path_db = _resolve_db_path(db_path)
    try:
        chunk = db.manager_chunk_insert(
            path_db,
            text=text.strip(),
            source=source,
            path=path,
            tags=tags,
        )
    except ValueError as exc:
        return {"статус": "error", "status": "error", "причина": str(exc), "reason": str(exc)}
    return {"статус": "ok", "id": chunk["id"], "чанк": chunk}


def manager_memory_search(
    query: str,
    source: Optional[str] = None,
    limit: int = 10,
    *,
    caller_role: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """FTS5-поиск чанков. Возвращает отсортированный по bm25-score список.

    Меньший score = более релевантный (стандарт FTS5). Архивные чанки
    исключаются. Пустой query → пустой список без ошибки.
    """
    deny = _check_manager_memory_role(caller_role)
    if deny is not None:
        return deny
    if source is not None and source not in _MANAGER_VALID_SOURCES_TOOLS:
        reason = f"неизвестный source: {source!r}"
        return {"статус": "error", "status": "error", "причина": reason, "reason": reason}
    if not isinstance(limit, int) or limit < 1:
        return {"статус": "error", "status": "error", "причина": "limit должен быть >= 1", "reason": "limit должен быть >= 1"}

    path_db = _resolve_db_path(db_path)
    try:
        chunks = db.manager_chunk_search(
            path_db, query=query, source=source, limit=limit
        )
    except ValueError as exc:
        return {"статус": "error", "status": "error", "причина": str(exc), "reason": str(exc)}
    return {"статус": "ok", "всего": len(chunks), "результаты": chunks}


def manager_memory_get(
    chunk_id: int,
    *,
    caller_role: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Прочитать один чанк по id. not_found если не существует."""
    deny = _check_manager_memory_role(caller_role)
    if deny is not None:
        return deny
    if not isinstance(chunk_id, int) or chunk_id < 1:
        return {"статус": "error", "status": "error", "причина": "id должен быть положительным int", "reason": "id должен быть положительным int"}

    path_db = _resolve_db_path(db_path)
    chunk = db.manager_chunk_get(path_db, chunk_id)
    if chunk is None:
        return {"статус": "not_found", "id": chunk_id}
    return {"статус": "ok", "чанк": chunk}


def manager_memory_recent(
    source: Optional[str] = None,
    limit: int = 20,
    *,
    caller_role: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Последние N чанков (updated_at DESC). Используется в bootstrap-режиме."""
    deny = _check_manager_memory_role(caller_role)
    if deny is not None:
        return deny
    if source is not None and source not in _MANAGER_VALID_SOURCES_TOOLS:
        reason = f"неизвестный source: {source!r}"
        return {"статус": "error", "status": "error", "причина": reason, "reason": reason}
    if not isinstance(limit, int) or limit < 1:
        return {"статус": "error", "status": "error", "причина": "limit должен быть >= 1", "reason": "limit должен быть >= 1"}

    path_db = _resolve_db_path(db_path)
    try:
        chunks = db.manager_chunk_recent(path_db, source=source, limit=limit)
    except ValueError as exc:
        return {"статус": "error", "status": "error", "причина": str(exc), "reason": str(exc)}
    return {"статус": "ok", "всего": len(chunks), "чанки": chunks}


def manager_memory_archive(
    chunk_id: int,
    *,
    caller_role: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Soft-delete чанка. not_found если чанка нет или он уже архивирован."""
    deny = _check_manager_memory_role(caller_role)
    if deny is not None:
        return deny
    if not isinstance(chunk_id, int) or chunk_id < 1:
        return {"статус": "error", "status": "error", "причина": "id должен быть положительным int", "reason": "id должен быть положительным int"}

    path_db = _resolve_db_path(db_path)
    ok = db.manager_chunk_archive(path_db, chunk_id)
    if not ok:
        return {"статус": "not_found", "id": chunk_id}
    return {"статус": "ok", "id": chunk_id}


# === 12. Planning sessions (B3, ADR-009 §2.4 + §2.6) ===
#
# 4 MCP-tools для Управляющего: list_all_inboxes / start_planning_session /
# collect_planning_responses / finalize_planning_session.
# Все четыре — gate на role.name='managing-director'.
#
# finalize_planning_session создаёт cross-task'и через тот же путь что и
# REST-endpoint /api/departments/<target>/tasks (см. dashboard/app.py
# api_create_inter_department_task) — прямым вызовом db.insert_task,
# requester_role_slug='managing-director', requester_department_id=NULL
# (Управляющий — глобальная роль, не привязан к отделу).


def _check_managing_director_role(caller_role: Optional[str]) -> Optional[dict[str, Any]]:
    """Возвращает 403-dict если caller не managing-director, иначе None.

    Используется для всех 4 planning-tools (B3) — обобщение паттерна из
    _check_manager_memory_role. Возвращаемый dict совместим со стилем
    остальных tool-функций (двуязычные ключи).
    """
    if caller_role != _MANAGER_MEMORY_ROLE:
        return _role_forbidden(caller_role)
    return None


def list_all_inboxes(
    *,
    caller_role: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Агрегат по всем отделам для Управляющего (ADR-009 §2.6).

    Для каждого активного отдела возвращает: dept_id, dept_name, wip, review,
    blocked counts (по задачам отдела), last_chat_msg_time (unix-ts последнего
    сообщения в чате отдела или None).

    Args:
        caller_role: должна быть 'managing-director'.

    Returns:
        {"статус": "ok", "всего": N, "inboxes": [...]} при успехе.
        {"статус": "forbidden", ...} если caller_role != managing-director.
    """
    deny = _check_managing_director_role(caller_role)
    if deny is not None:
        return deny
    path_db = _resolve_db_path(db_path)
    inboxes = db.inbox_summary(path_db)
    return {"статус": "ok", "всего": len(inboxes), "inboxes": inboxes}


def start_planning_session(
    owner_request: str,
    departments: list[str],
    *,
    caller_role: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Phase 1: создать planning_session и пригласить лидов отделов в чат.

    Создаёт запись planning_sessions(phase='gathering'). Для каждого отдела
    в списке `departments` отправляет chat_post (author='managing-director',
    department_id=<dept>) с приглашением.

    Args:
        owner_request: исходное сообщение owner-а (требование, контекст).
        departments: список dept_id отделов, чьи лиды зовутся на планёрку.
        caller_role: должна быть 'managing-director'.

    Returns:
        {"статус": "ok", "session_id": "...", "сессия": {...},
         "приглашения": [{"dept_id": ..., "message_id": ...}, ...]}
        {"статус": "forbidden", ...} если caller_role != managing-director.
        {"статус": "error", ...} при пустых параметрах или несуществующем dept.
    """
    deny = _check_managing_director_role(caller_role)
    if deny is not None:
        return deny

    if not owner_request or not owner_request.strip():
        return {"статус": "error", "status": "error", "причина": "owner_request пустой", "reason": "owner_request пустой"}
    if not isinstance(departments, list) or len(departments) == 0:
        return {"статус": "error", "status": "error", "причина": "departments должен быть непустым списком", "reason": "departments должен быть непустым списком"}

    path_db = _resolve_db_path(db_path)

    # Проверяем что все отделы существуют (защита от опечаток в slug).
    for dept_id in departments:
        if not isinstance(dept_id, str) or not dept_id.strip():
            return {"статус": "error", "status": "error", "причина": f"невалидный dept_id: {dept_id!r}", "reason": f"невалидный dept_id: {dept_id!r}"}
        dept = db.get_department(path_db, dept_id)
        if dept is None:
            return {"статус": "error", "status": "error", "причина": f"отдел {dept_id!r} не существует", "reason": f"отдел {dept_id!r} не существует"}

    # Создаём запись планёрки.
    try:
        session = db.planning_session_create(
            path_db,
            owner_request=owner_request.strip(),
            departments=list(departments),
            phase="gathering",
        )
    except ValueError as exc:
        return {"статус": "error", "status": "error", "причина": str(exc), "reason": str(exc)}

    # Постим приглашение в чат каждого отдела. Если один из chat_post упал —
    # не откатываем, продолжаем (планёрка уже создана; ошибка лидера будет
    # видна управляющему). Возвращаем список с message_id для каждого dept.
    invitations: list[dict[str, Any]] = []
    invite_text = (
        f"🤔 Планёрка #{session['id'][:6]}: {owner_request.strip()}\n"
        f"Поделись инсайтами и вопросами в этом чате — Управляющий соберёт."
    )
    for dept_id in departments:
        try:
            msg = db.post_chat_message(
                path_db, "managing-director", invite_text, department_id=dept_id
            )
            invitations.append({"dept_id": dept_id, "message_id": msg["id"]})
        except ValueError as exc:
            invitations.append({"dept_id": dept_id, "error": str(exc)})

    return {
        "статус": "ok",
        "session_id": session["id"],
        "сессия": session,
        "приглашения": invitations,
    }


def collect_planning_responses(
    planning_session_id: str,
    *,
    caller_role: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Phase 2: собрать реплики лидов из чатов отделов в discussion_log.

    Читает chat_recent каждого отдела из planning_sessions.departments_involved
    начиная с started_at. Собирает реплики в JSON-массив
    [{author, role, dept, text, ts}, ...] и обновляет discussion_log + phase='discussion'.

    Сообщения от author='managing-director' исключаются (это его собственные
    приглашения, не реплики лидов).

    Args:
        planning_session_id: id планёрки (из start_planning_session).
        caller_role: должна быть 'managing-director'.

    Returns:
        {"статус": "ok", "сессия": {...с обновлённым discussion_log}, "discussion_log": [...]}
        {"статус": "forbidden", ...} если caller_role != managing-director.
        {"статус": "not_found", ...} если планёрка не найдена.
    """
    deny = _check_managing_director_role(caller_role)
    if deny is not None:
        return deny
    if not planning_session_id or not planning_session_id.strip():
        return {"статус": "error", "status": "error", "причина": "planning_session_id пустой", "reason": "planning_session_id пустой"}

    path_db = _resolve_db_path(db_path)
    session = db.planning_session_get(path_db, planning_session_id.strip())
    if session is None:
        return {"статус": "not_found", "planning_session_id": planning_session_id}

    started_at: int = session["started_at"]
    departments = session.get("departments_involved") or []

    discussion_log: list[dict[str, Any]] = []
    for dept_id in departments:
        msgs = db.list_chat_messages(
            path_db, since=started_at, limit=500, department_id=dept_id
        )
        for m in msgs:
            # Исключаем приглашения самого Управляющего, чтобы лог содержал
            # только реплики лидов и других участников.
            if m["author"] == "managing-director":
                continue
            discussion_log.append({
                "author": m["author"],
                "role":   m["author"],   # alias — author == role.name в Devboard
                "dept":   dept_id,
                "text":   m["text"],
                "ts":     m["created_at"],
            })
    # Сортируем хронологически — реплики из разных чатов смешиваются по ts.
    discussion_log.sort(key=lambda x: x["ts"])

    try:
        updated = db.planning_session_update(
            path_db,
            planning_session_id.strip(),
            discussion_log=discussion_log,
            phase="discussion",
        )
    except ValueError as exc:
        return {"статус": "error", "status": "error", "причина": str(exc), "reason": str(exc)}

    return {
        "статус": "ok",
        "сессия": updated,
        "discussion_log": discussion_log,
    }


def _parse_owner_answer_into_tasks(owner_answer: str, departments: list[str]) -> list[dict[str, Any]]:
    """Парсит owner_answer на список задач для каждого отдела.

    Простая эвристика: разделяем по строкам формата `<dept>:` или
    `<dept> -` в начале строки. Если эвристика не сработала — создаём
    одну задачу с полным текстом owner_answer для каждого dept (fallback).

    Возвращает [{"dept": "marketing", "title": "...", "description": "..."}, ...].
    """
    tasks: list[dict[str, Any]] = []
    text = (owner_answer or "").strip()
    if not text:
        return tasks

    # Карта lowercase dept_id → оригинальный slug.
    dept_map = {d.lower(): d for d in departments}

    # Pattern: строка начинается с "<dept>:" или "<dept> -" или "<dept>—" (em-dash).
    # Жадно матчим заголовок раздела, потом до следующего такого заголовка.
    lines = text.splitlines()
    current_dept: Optional[str] = None
    buffers: dict[str, list[str]] = {d: [] for d in departments}

    def _header_dept(line: str) -> Optional[str]:
        s = line.strip()
        if not s:
            return None
        # Ищем "<dept>:" в начале строки.
        m = re.match(r"^\*{0,2}([\w-]+)\*{0,2}\s*[:\-—]", s)
        if not m:
            return None
        candidate = m.group(1).lower()
        return dept_map.get(candidate)

    for line in lines:
        dept_header = _header_dept(line)
        if dept_header is not None:
            current_dept = dept_header
            # Удаляем заголовок из контента — оставляем остаток строки.
            stripped = re.sub(
                r"^\*{0,2}[\w-]+\*{0,2}\s*[:\-—]\s*",
                "",
                line.strip(),
                count=1,
            )
            if stripped:
                buffers[current_dept].append(stripped)
        else:
            if current_dept is not None:
                buffers[current_dept].append(line)

    # Собираем задачи только для отделов, у которых что-то есть.
    for dept_id, lines_buf in buffers.items():
        content = "\n".join(lines_buf).strip()
        if content:
            # Title — первая строка (укороченная), description — полный блок.
            first_line = next((ln.strip() for ln in lines_buf if ln.strip()), "")
            title = first_line[:120] if first_line else f"Задача из планёрки для {dept_id}"
            tasks.append({
                "dept":        dept_id,
                "title":       title,
                "description": content,
            })

    # Fallback: ни одного заголовка не нашли — раскидываем весь текст по всем отделам.
    if not tasks:
        for dept_id in departments:
            tasks.append({
                "dept":        dept_id,
                "title":       (text.splitlines()[0] if text else "Задача из планёрки")[:120],
                "description": text,
            })

    return tasks


def finalize_planning_session(
    planning_session_id: str,
    owner_answer: str,
    *,
    caller_role: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Phase 4: распределение — создаёт cross-task в каждый отдел.

    Парсит owner_answer на N задач (по dept'ам), для каждой создаёт задачу
    через db.insert_task с requester_role_slug='managing-director'
    (Управляющий — глобальная роль, без requester_department_id).
    Обновляет planning_sessions: phase='done', finished_at=now, owner_answer,
    created_tasks=[{dept, task_id}, ...].

    Args:
        planning_session_id: id планёрки.
        owner_answer: ответ owner'а на questions_for_owner. Может содержать
            заголовки секций вида "marketing:", "dev -", "legal —" — тогда
            каждой секции = одна задача в соответствующий отдел. Если без
            заголовков — одна общая задача каждому отделу (fallback).
        caller_role: должна быть 'managing-director'.

    Returns:
        {"статус": "ok", "created_tasks": [{"dept":..., "task_id":...}], "сессия": {...}}
        {"статус": "forbidden", ...} если caller_role != managing-director.
        {"статус": "not_found", ...} если планёрка не найдена.
    """
    deny = _check_managing_director_role(caller_role)
    if deny is not None:
        return deny
    if not planning_session_id or not planning_session_id.strip():
        return {"статус": "error", "status": "error", "причина": "planning_session_id пустой", "reason": "planning_session_id пустой"}
    if not owner_answer or not owner_answer.strip():
        return {"статус": "error", "status": "error", "причина": "owner_answer пустой", "reason": "owner_answer пустой"}

    path_db = _resolve_db_path(db_path)
    session = db.planning_session_get(path_db, planning_session_id.strip())
    if session is None:
        return {"статус": "not_found", "planning_session_id": planning_session_id}

    departments = session.get("departments_involved") or []
    if not departments:
        return {"статус": "error", "status": "error", "причина": "у планёрки нет departments_involved", "reason": "у планёрки нет departments_involved"}

    # Парсим owner_answer на N задач.
    parsed_tasks = _parse_owner_answer_into_tasks(owner_answer.strip(), list(departments))

    # Описание включает контекст планёрки — куда смотреть, кто инициатор.
    owner_request = session.get("owner_request", "")
    created: list[dict[str, Any]] = []

    for t in parsed_tasks:
        dept_id = t["dept"]
        # Защита: вдруг dept_id отсутствует в БД (теоретически нет, мы валидировали при start).
        if db.get_department(path_db, dept_id) is None:
            created.append({"dept": dept_id, "error": "department_not_found"})
            continue
        full_desc = (
            f"{t['description']}\n\n"
            f"---\n"
            f"_Создано Управляющим по итогам планёрки #{session['id'][:6]}._\n"
            f"_Исходный запрос owner-а:_ {owner_request}"
        )
        try:
            task = db.insert_task(
                path_db,
                title=t["title"],
                description=full_desc,
                assignee=None,
                reporter="managing-director",
                priority="P2",
                department_id=dept_id,
                # ADR-009 §2.6 + ADR-005: Управляющий — глобальная роль, requester_department_id=NULL.
                requester_department_id=None,
                requester_role_slug="managing-director",
                labels=["from-planning", f"planning:{session['id']}"],
                status="todo",
            )
            created.append({"dept": dept_id, "task_id": task["id"]})
        except Exception as exc:  # noqa: BLE001
            created.append({"dept": dept_id, "error": str(exc)})

    import time as _time
    now = int(_time.time())
    try:
        updated = db.planning_session_update(
            path_db,
            planning_session_id.strip(),
            phase="done",
            owner_answer=owner_answer.strip(),
            created_tasks=created,
            finished_at=now,
        )
    except ValueError as exc:
        return {"статус": "error", "status": "error", "причина": str(exc), "reason": str(exc)}

    return {
        "статус": "ok",
        "status": "done",
        "created_tasks": created,
        "сессия": updated,
    }


# === 13. parse_task_description ===


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

"""HR pipeline runner — S10.3 (ADR-004 §2.2).

Управляет жизненным циклом HR-сессии: спавнит `claude` CLI как subprocess с
HR system-prompt'ом, ведёт state machine в таблице `hr_sessions`, прокидывает
owner-сообщения через stdin, валидирует HR-план перед активацией и материализует
роли в `roles/<dept-slug>/<role-slug>.md` при approve.

Состояния (см. ADR-004 §2.2):
    hr_planning            — спавн HR-сессии, ждём первый план
    awaiting_owner_review  — план готов, owner смотрит
    hr_revising            — owner прислал правки, HR перегенерирует
    hr_activating          — owner approved, идёт активация (валидация + запись)
    active                 — отдел создан, файлы и БД-запись на месте
    aborted                — отказ owner'а / валидация провалилась 3 раза подряд

В этом модуле НЕТ Flask-зависимостей и НЕТ маршрутов — это чистый
runner-слой. Endpoints живут в `app.py`.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path
from threading import Lock
from typing import Any, Optional

# Гарантируем что mcp_server/ в sys.path для `from pride_tasks import db`.
_MCP_DIR = Path(__file__).resolve().parent.parent / "mcp_server"
if str(_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_MCP_DIR))

from pride_tasks import db  # noqa: E402

log = logging.getLogger("pride_dashboard.hr")

# Корень репо (родитель dashboard/).
_REPO_ROOT = Path(__file__).resolve().parent.parent

# Каталог HR system-prompt'а.
_HR_PROMPT_PATH = _REPO_ROOT / "roles" / "hr.md"

# Каталог куда HR пишет роли при активации.
_ROLES_DIR = _REPO_ROOT / "roles"

# Максимум попыток валидации плана на этапе approve.
HR_MAX_VALIDATION_ATTEMPTS = 3

# Регексп для slug отдела на диск: lower, ascii letters/digits/dash.
_DEPT_SLUG_RE = re.compile(r"[^a-z0-9-]")


# Локальный реестр активных subprocess'ов: {hr_session_id: Popen}.
# Не персистентный — при перезапуске процесса дашборда теряется (это OK для S10.3:
# UI заметит через GET /status что плана нет и спросит у owner restart).
_subprocs: dict[str, subprocess.Popen] = {}
_subprocs_lock = Lock()


# ---------------------------------------------------------------------------
# Subprocess management
# ---------------------------------------------------------------------------


def _hr_system_prompt_text() -> str:
    """Прочитать содержимое roles/hr.md. Если файла нет — заглушка.

    HR system-prompt в claude CLI передаётся через --append-system-prompt.
    """
    try:
        return _HR_PROMPT_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning("roles/hr.md недоступен (%s) — будет использован пустой prompt", exc)
        return ""


def _build_claude_cmd(prompt_text: str, mcp_config: str, initial_message: str) -> list[str]:
    """Команда запуска claude CLI с HR system-prompt и полным набором флагов.

    Используем PRIDE_HR_CLAUDE_CMD env override для тестов / нестандартных путей.
    По умолчанию — `claude` в PATH.
    """
    override = os.environ.get("PRIDE_HR_CLAUDE_CMD")
    if override:
        # Разрешаем "python -u fake.py" и т.п.
        return shlex.split(override) + [
            "--append-system-prompt", prompt_text,
            "--mcp-config", mcp_config,
            "--permission-mode", "bypassPermissions",
            "--model", "claude-opus-4-7",
            "--output-format", "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--print", initial_message,
        ]
    return [
        "claude",
        "--append-system-prompt", prompt_text,
        "--mcp-config", mcp_config,
        "--permission-mode", "bypassPermissions",
        "--model", "claude-opus-4-7",
        "--output-format", "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--print", initial_message,
    ]


def _extract_plan_json(text: str) -> dict | None:
    """Извлечь ```json ... ``` блок из chat_post.text и распарсить."""
    m = re.search(r"```json\s*\n(.*?)\n```", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _hr_stream_reader(session_id: str, proc: subprocess.Popen, db_path: Path) -> None:
    """Читает stream-json stdout HR claude subprocess.

    Ищет tool_use chat_post → извлекает план JSON, обновляет state в БД.
    При завершении subprocess без плана → state='failed'.
    """
    for line in iter(proc.stdout.readline, ""):
        if not line:
            break
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "assistant":
            for block in event.get("message", {}).get("content", []):
                if (
                    block.get("type") == "tool_use"
                    and block.get("name") == "mcp__pride-tasks__chat_post"
                ):
                    text = block.get("input", {}).get("text", "")
                    plan = _extract_plan_json(text)
                    if plan:
                        db.update_hr_session(
                            db_path,
                            session_id,
                            state="awaiting_owner_review",
                            plan_json=json.dumps(plan, ensure_ascii=False),
                        )
                        break
        if event.get("type") == "result":
            sess = db.get_hr_session(db_path, session_id)
            if sess and sess.get("state") == "hr_planning":
                db.update_hr_session(
                    db_path,
                    session_id,
                    state="aborted",
                    last_message="HR subprocess finished without publishing plan",
                )


def spawn_hr_subprocess(
    session_id: str,
    initial_message: str,
    *,
    db_path: Optional[Path] = None,
    popen_factory: Any = subprocess.Popen,
) -> Optional[subprocess.Popen]:
    """Спавнит claude CLI как subprocess для HR-сессии.

    db_path — путь к SQLite БД (передаётся в reader thread для обновления state).
    popen_factory — точка инъекции для тестов (mock'аем Popen).
    Возвращает Popen или None если spawn упал (логируем, не raise).
    """
    prompt_text = _hr_system_prompt_text()
    # Путь к .mcp.json: PRIDE_MCP_CONFIG env или корень репо.
    mcp_config = os.environ.get(
        "PRIDE_MCP_CONFIG", str(_REPO_ROOT / ".mcp.json")
    )
    cmd = _build_claude_cmd(prompt_text, mcp_config, initial_message)
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env["PYTHONUTF8"] = "1"
    try:
        proc = popen_factory(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,  # line-buffered
        )
    except (OSError, FileNotFoundError) as exc:
        log.error("spawn HR claude CLI failed: %s (cmd=%s)", exc, cmd)
        return None

    with _subprocs_lock:
        _subprocs[session_id] = proc

    # Запускаем reader thread для парсинга stream-json и обновления state в БД.
    if db_path is not None:
        reader = threading.Thread(
            target=_hr_stream_reader,
            args=(session_id, proc, db_path),
            daemon=True,
            name=f"hr-stream-reader-{session_id[:8]}",
        )
        reader.start()

    return proc


def respawn_hr_for_revise(
    session_id: str,
    owner_comment: str,
    *,
    db_path: Optional[Path] = None,
    popen_factory: Any = subprocess.Popen,
) -> Optional[subprocess.Popen]:
    """Спавнит новый HR subprocess для revision по owner-комментарию.

    Закрывает старый subprocess (если жив), формирует initial_message с
    предыдущим планом и owner-комментом, спавнит новый subprocess и обновляет
    state в БД: hr_planning, iteration_count + 1.

    db_path — путь к SQLite БД.
    popen_factory — точка инъекции для тестов (mock'аем Popen).
    Возвращает Popen или None если spawn упал.
    """
    if db_path is None:
        log.warning("respawn_hr_for_revise: db_path не передан, revision невозможен")
        return None

    sess = db.get_hr_session(db_path, session_id)
    if sess is None:
        log.warning("respawn_hr_for_revise: сессия %s не найдена", session_id)
        return None

    prev_plan = sess.get("plan_json") or "{}"
    # Используем iteration_count как номер ревизии (нет отдельной колонки revision).
    current_revision = sess.get("iteration_count", 0) + 1

    initial_message = (
        f"Owner запросил revision к предыдущему плану.\n\n"
        f"Предыдущий план (Plan v{current_revision}):\n"
        f"```json\n{prev_plan}\n```\n\n"
        f"Комментарий owner'а:\n{owner_comment}\n\n"
        f"Опубликуй Plan v{current_revision + 1} через chat_post с обновлённым ```json``` блоком."
    )

    # Закрываем старый subprocess перед спавном нового.
    close_hr_subprocess(session_id)

    prompt_text = _hr_system_prompt_text()
    mcp_config = os.environ.get("PRIDE_MCP_CONFIG", str(_REPO_ROOT / ".mcp.json"))
    cmd = _build_claude_cmd(prompt_text, mcp_config, initial_message)
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env["PYTHONUTF8"] = "1"

    try:
        proc = popen_factory(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except (OSError, FileNotFoundError) as exc:
        log.error("respawn HR claude CLI failed: %s (cmd=%s)", exc, cmd)
        return None

    with _subprocs_lock:
        _subprocs[session_id] = proc

    reader = threading.Thread(
        target=_hr_stream_reader,
        args=(session_id, proc, db_path),
        daemon=True,
        name=f"hr-stream-reader-{session_id[:8]}",
    )
    reader.start()

    db.update_hr_session(
        db_path,
        session_id,
        state="hr_planning",
        iteration_count=current_revision,
        last_message=owner_comment,
    )

    return proc


def send_to_hr_subprocess(session_id: str, message: str) -> bool:
    """Передать owner-сообщение в stdin активного HR subprocess.

    Возвращает True если запись прошла, False если процесса нет / упал.
    """
    with _subprocs_lock:
        proc = _subprocs.get(session_id)
    if proc is None or proc.poll() is not None:
        return False
    if proc.stdin is None:
        return False
    try:
        proc.stdin.write(message + "\n")
        proc.stdin.flush()
        return True
    except (BrokenPipeError, OSError) as exc:
        log.warning("HR stdin write failed for session %s: %s", session_id, exc)
        return False


def close_hr_subprocess(session_id: str) -> None:
    """Аккуратно закрыть subprocess: close stdin, wait с таймаутом, kill при таймауте."""
    with _subprocs_lock:
        proc = _subprocs.pop(session_id, None)
    if proc is None:
        return
    try:
        if proc.stdin is not None:
            try:
                proc.stdin.close()
            except OSError:
                pass
        # Дадим CLI 3 секунды чтобы спокойно завершиться.
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
    except Exception as exc:  # noqa: BLE001 -- best-effort cleanup
        log.warning("close_hr_subprocess(%s): %s", session_id, exc)


# ---------------------------------------------------------------------------
# Plan materialization
# ---------------------------------------------------------------------------


def department_slug(name: str) -> str:
    """Преобразовать имя отдела в slug на диск: lower-case ASCII.

    Не-ASCII символы транслитерируются грубо: убираются. Если после
    очистки пусто — fallback на 'dept-<short_id>'.
    """
    s = name.strip().lower()
    s = s.replace(" ", "-")
    # Только latin / digit / dash
    s = _DEPT_SLUG_RE.sub("", s)
    s = re.sub(r"-+", "-", s).strip("-")
    if not s:
        # transliteration fallback: используем хэш id
        s = "dept"
    return s


def _format_role_md(role: dict[str, Any], department_name: str) -> str:
    """Сформировать markdown-файл роли (frontmatter + body) для записи на диск.

    Frontmatter — минимально совместимый с ADR-002 (RoleConfig).
    Body — system_prompt из плана.
    """
    slug = role["slug"]
    name_ru = role.get("name_ru", slug)
    description = (role.get("output_spec") or "").strip()
    # description в frontmatter — single-line, ≤ 100 символов.
    one_line = " ".join(description.split())
    if len(one_line) > 100:
        one_line = one_line[:97] + "..."
    if not one_line:
        one_line = f"{name_ru} в отделе {department_name}"

    body = role.get("system_prompt") or role.get("system_prompt_template") or (
        f"# Ты — {name_ru}\n\n"
        f"Роль в отделе \"{department_name}\". См. output_spec в frontmatter."
    )

    model = role.get("model", "claude-sonnet-4-6")
    frontmatter_lines = [
        "---",
        "schema_version: 1",
        f"name: {slug}",
        f"description: {one_line}",
        "llm: claude",
        f"model: {model}",
        'tools: "*"',
        "temperature: 0.3",
        "max_tokens: 8192",
        "extras:",
        "  hr_meta:",
        f"    department_name: {department_name!r}",
        f"    is_lead: {bool(role.get('is_lead'))}",
        "---",
    ]
    return "\n".join(frontmatter_lines) + "\n\n" + body + "\n"


def materialize_roles(
    plan: dict[str, Any],
    *,
    roles_dir: Path = _ROLES_DIR,
) -> tuple[list[Path], list[str]]:
    """Записать роли из плана в roles/<dept-slug>/<role-slug>.md.

    Используется при approve (state=hr_activating). Возвращает
    (созданные_файлы, ошибки). Если ошибки непусты — каталог отдела удаляется
    (rollback) и список созданных файлов будет пустым.
    """
    dept = plan.get("department") or {}
    dept_name = dept.get("name", "Unknown")
    dept_slug = department_slug(dept_name)
    target_dir = Path(roles_dir) / dept_slug

    created: list[Path] = []
    errors: list[str] = []

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return [], [f"cannot create {target_dir}: {exc}"]

    for role in plan.get("roles") or []:
        try:
            md = _format_role_md(role, dept_name)
            fp = target_dir / f"{role['slug']}.md"
            fp.write_text(md, encoding="utf-8")
            created.append(fp)
        except (OSError, KeyError) as exc:
            errors.append(f"role {role.get('slug', '?')}: {exc}")

    if errors:
        # Rollback — удаляем уже созданные файлы и пытаемся убрать каталог
        # если он стал пустым.
        for f in created:
            try:
                f.unlink()
            except OSError:
                pass
        try:
            target_dir.rmdir()
        except OSError:
            pass
        return [], errors

    return created, []


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _reset_state_for_tests() -> None:
    """Очистить локальный реестр subprocess'ов. Только для pytest!"""
    with _subprocs_lock:
        for proc in list(_subprocs.values()):
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
        _subprocs.clear()


# Безусловно экспортируем константы, которые используются и в app.py, и в тестах.
__all__ = [
    "HR_MAX_VALIDATION_ATTEMPTS",
    "spawn_hr_subprocess",
    "respawn_hr_for_revise",
    "send_to_hr_subprocess",
    "close_hr_subprocess",
    "materialize_roles",
    "department_slug",
    "_build_claude_cmd",
    "_extract_plan_json",
    "_hr_stream_reader",
    "_reset_state_for_tests",
    "_subprocs",
]

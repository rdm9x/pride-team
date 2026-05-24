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
import time
from pathlib import Path
from threading import Lock
from typing import Any, Optional

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


def _build_claude_cmd(prompt_text: str) -> list[str]:
    """Команда запуска claude CLI с HR system-prompt.

    Используем PRIDE_HR_CLAUDE_CMD env override для тестов / нестандартных путей.
    По умолчанию — `claude` в PATH.
    """
    override = os.environ.get("PRIDE_HR_CLAUDE_CMD")
    if override:
        # Разрешаем "python -u fake.py" и т.п.
        return shlex.split(override) + ["--append-system-prompt", prompt_text]
    return ["claude", "--append-system-prompt", prompt_text]


def spawn_hr_subprocess(
    session_id: str,
    initial_message: str,
    *,
    popen_factory: Any = subprocess.Popen,
) -> Optional[subprocess.Popen]:
    """Спавнит claude CLI как subprocess для HR-сессии.

    popen_factory — точка инъекции для тестов (mock'аем Popen).
    Возвращает Popen или None если spawn упал (логируем, не raise).
    """
    prompt_text = _hr_system_prompt_text()
    cmd = _build_claude_cmd(prompt_text)
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

    # Передаём начальное сообщение (description от owner'а).
    if initial_message and proc.stdin is not None:
        try:
            proc.stdin.write(initial_message + "\n")
            proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            log.warning("HR stdin write failed: %s", exc)

    with _subprocs_lock:
        _subprocs[session_id] = proc
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
    "send_to_hr_subprocess",
    "close_hr_subprocess",
    "materialize_roles",
    "department_slug",
    "_reset_state_for_tests",
    "_subprocs",
]

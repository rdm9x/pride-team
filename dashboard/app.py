"""Flask-дашборд малой команды devboard.

Запуск:
    cd devboard/dashboard && uv run python app.py
    или через ../commands/devboard-start.sh

API — см. AGENTS.md §REST endpoints.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from queue import Empty, Queue
from threading import Lock, Thread
from typing import Any, Optional

# Кириллица в пути ломает editable .pth — импортируем devboard_tasks по абсолютному
# пути (паттерн из pride_mcp/server.py).
_MCP_DIR = Path(__file__).resolve().parent.parent / "mcp_server"
if str(_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_MCP_DIR))

# roles/ package lives at repo root — add it so `from roles.validator import ...` works
_REPO_ROOT_EARLY = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT_EARLY) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT_EARLY))

from flask import Flask, Response, jsonify, render_template, request  # noqa: E402

from devboard_tasks import db, tools  # noqa: E402

# S10.3 (ADR-004): HR pipeline runner и валидатор плана.
import hr as hr_runner  # noqa: E402
from roles.validator import validate_hr_plan  # noqa: E402

logging.basicConfig(
    level=os.environ.get("DEVBOARD_DASHBOARD_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("pride_dashboard")

# === Пути ===

_REPO_ROOT = Path(__file__).resolve().parent.parent  # devboard root
_DATA_DIR = _REPO_ROOT / "data"
_ROLES_DIR = _REPO_ROOT / "roles"
_COMMANDS_DIR = _REPO_ROOT / "commands"
_TEMPLATES_DIR = _REPO_ROOT / "templates" / "departments"
_VENDORED_KWP_DIR = _REPO_ROOT / "vendored" / "knowledge-work-plugins"
_PID_FILE = _DATA_DIR / "team.pid"
_LIVE_LOG = _DATA_DIR / "team.log"

DB_PATH = db.default_db_path()
db.init_db(DB_PATH)
log.info("дашборд использует БД: %s", DB_PATH)

# === Управление сессией тимлида (subprocess) ===

_team_state: dict[str, Any] = {
    "process": None,            # subprocess.Popen | None
    "queue": Queue(),           # очередь строк stdout/stderr для SSE
    "started_at": None,
    "lock": Lock(),
    "auto_mode": False,         # авто-запуск следующей сессии после завершения
    "starts_history": [],       # timestamps последних запусков (для rate-limit)
    "auto_pause_reason": None,  # если auto заблокирован — почему
    "reader_thread": None,      # Thread | None — текущий _stream_reader (S17.3 fix)
}

# Лимиты авто-режима (защита от инфинит-лупа)
_AUTO_MIN_INTERVAL_SEC = 30          # минимум между запусками
_AUTO_MAX_PER_HOUR = 20              # не больше 20 сессий в час
_AUTO_CHECK_INTERVAL_SEC = 10        # как часто monitor-thread проверяет


def _format_stream_event(raw: str) -> Optional[str]:
    """Превращает stream-json событие в человекочитаемую строку.

    Показывает: что тимлид думает (text), какие важные действия делает
    (делегирование, создание/закрытие задач, уведомления).

    НЕ показывает: служебные tool_use (чтение канбана, чтение файлов),
    tool_result, system/init, stream_event. Это всё есть в data/team.log
    в сыром виде.
    """
    raw = raw.strip()
    if not raw:
        return None
    if not raw.startswith("{"):
        return None  # сырой текст не показываем — это шум

    try:
        ev = json.loads(raw)
    except json.JSONDecodeError:
        return None

    et = ev.get("type")
    if et == "assistant":
        msg = ev.get("message", {})
        out = []
        for block in msg.get("content", []):
            btype = block.get("type")
            if btype == "text":
                txt = (block.get("text") or "").strip()
                if txt:
                    out.append(f"🧭  {txt}")
            elif btype == "tool_use":
                human = _humanize_tool(block.get("name", ""), block.get("input", {}))
                if human:
                    out.append(human)
        return "\n".join(out) if out else None

    if et == "result":
        # Финал сессии — записываем стат в БД и показываем человеческую сводку
        try:
            usage = ev.get("usage", {}) or {}
            _record_session_from_result(ev, usage)
        except Exception as exc:  # noqa: BLE001
            log.warning("не смог записать claude_session: %s", exc)
        dur = ev.get("duration_ms", 0) / 1000
        if dur >= 60:
            dur_s = f"{int(dur // 60)}м {int(dur % 60)}с"
        else:
            dur_s = f"{int(dur)}с"
        is_error = ev.get("is_error")
        marker = "✗ Сессия завершилась с ошибкой" if is_error else "✓ Сессия закончена"
        return f"{marker} · длилась {dur_s}"

    # system/init, user (tool_result), stream_event — не показываем
    return None


# Карта tool_name → как красиво описать пользователю.
# Возвращаем None если событие неинтересное (чтение, рутина) — оно не попадёт в UI.
def _humanize_tool(name: str, inp: dict) -> Optional[str]:
    inp = inp or {}

    # === MCP devboard-tasks: интересные действия ===

    if name == "mcp__devboard-tasks__create_task":
        title = _trim(inp.get("title", ""), 70)
        assignee = inp.get("assignee") or "не назначено"
        return f"📝  Создаёт задачу для {assignee}: «{title}»"

    if name == "mcp__devboard-tasks__update_task":
        new_status = inp.get("status")
        tid = (inp.get("task_id") or "")[:6]
        if new_status == "done":
            return f"✅  Закрывает задачу #{tid}"
        if new_status == "review":
            return f"📤  Отправляет #{tid} на приёмку"
        if new_status == "wip":
            return f"▶️  Берёт #{tid} в работу"
        if new_status == "blocked":
            return f"🛑  Блокирует #{tid}"
        return None  # переименование / другие правки — шум

    if name == "mcp__devboard-tasks__claim_task":
        tid = (inp.get("task_id") or "")[:6]
        return f"🤝  Берёт задачу #{tid}"

    if name == "mcp__devboard-tasks__add_comment":
        tid = (inp.get("task_id") or "")[:6]
        text = _trim(inp.get("text", ""), 80)
        return f"💬  Комментирует #{tid}: «{text}»"

    if name == "mcp__devboard-tasks__submit_result":
        tid = (inp.get("task_id") or "")[:6]
        return f"📦  Сдаёт результат по #{tid}"

    if name == "mcp__devboard-tasks__add_dependency":
        a = (inp.get("task_id") or "")[:6]
        b = (inp.get("depends_on") or "")[:6]
        return f"🔗  Связь: #{a} ждёт #{b}"

    if name == "mcp__devboard-tasks__chat_post":
        # В чат — уже видно в правой панели, дублировать не надо
        return None

    if name == "mcp__devboard-tasks__notify_user":
        text = _trim(inp.get("text", ""), 80)
        return f"🔔  Telegram пользователю: «{text}»"

    # === Task tool — самое важное (запуск подчинённых) ===

    if name == "Task":
        desc = _trim(inp.get("description", ""), 80)
        prompt = inp.get("prompt", "")
        # Ищем какая роль в prompt'е (содержимое одного из roles/*.md)
        role = "подчинённого"
        for r in ("бэкенд", "qa", "архитектор", "frontend", "devops", "техписатель"):
            if r in prompt[:500].lower():
                role = r
                break
        return f"👥  Делегирует {role}у: «{desc}»"

    # === Чтение / навигация — НЕ показываем ===

    if name in (
        "mcp__devboard-tasks__list_tasks",
        "mcp__devboard-tasks__get_task",
        "mcp__devboard-tasks__chat_recent",
        "mcp__devboard-tasks__get_dependencies",
        "mcp__devboard-tasks__list_roles",
        "Read", "Glob", "Grep",
    ):
        return None

    # === Файловые / shell — упомянем, без деталей ===

    if name == "Write":
        path = _trim(inp.get("file_path", ""), 60)
        return f"📄  Создаёт файл {path}"

    if name == "Edit":
        path = _trim(inp.get("file_path", ""), 60)
        return f"✏️  Правит файл {path}"

    if name == "Bash":
        cmd = _trim(inp.get("command", ""), 80)
        return f"⚡  Запускает: {cmd}"

    # === Остальные tool'ы — игнорируем ===
    return None


def _trim(value, n: int = 60) -> str:
    s = str(value).replace("\n", " ")
    return (s[:n] + "…") if len(s) > n else s


def _record_session_from_result(ev: dict, usage: dict) -> None:
    """Сохраняет stream-json result-событие в claude_sessions.

    Корректно считает input-токены: суммирует все три источника (обычные,
    cache_creation, cache_read). Раньше учитывался только usage.input_tokens
    что давало искажённую картину (output >> input).
    """
    now = int(time.time())
    duration_ms = int(ev.get("duration_ms") or 0)
    started_at = now - max(1, duration_ms // 1000)

    # Реальный input = обычные input-токены + создание кеша + чтение кеша.
    input_tokens = (
        (usage.get("input_tokens") or 0)
        + (usage.get("cache_creation_input_tokens") or 0)
        + (usage.get("cache_read_input_tokens") or 0)
    )

    # Модель: stream-json у claude-code 2.x кладёт её в `modelUsage` —
    # это dict вида {model_name: {inputTokens, outputTokens, costUSD, ...}}.
    # Claude Code дополнительно использует Haiku для compaction / title-gen,
    # поэтому Haiku появляется почти в каждой сессии (~$0.001). Выбираем
    # PRIMARY MODEL — ту что съела больше всего costUSD (это реальный тимлид).
    model = ev.get("model")
    if not model:
        mu = ev.get("modelUsage") or {}
        if isinstance(mu, dict) and mu:
            model = max(
                mu.keys(),
                key=lambda k: (mu[k] or {}).get("costUSD") or 0,
            )

    db.record_claude_session(
        DB_PATH,
        started_at=started_at,
        finished_at=now,
        duration_ms=duration_ms,
        num_turns=ev.get("num_turns"),
        input_tokens=input_tokens or None,
        output_tokens=usage.get("output_tokens"),
        total_cost_usd=ev.get("total_cost_usd"),
        model=model,
        is_error=bool(ev.get("is_error")),
    )


def _start_backup_thread(db_path: Path) -> None:
    """Раз в час делает SQLite-бекап в data/backups/. Хранит 7 дней.

    Бекап через sqlite3 .backup — корректен под WAL, не блокирует писателей.
    """
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    def loop() -> None:
        import sqlite3 as _sql
        while True:
            time.sleep(3600)  # каждый час
            try:
                stamp = time.strftime("%Y%m%d-%H%M")
                target = backup_dir / f"tasks-{stamp}.db"
                src = _sql.connect(str(db_path))
                dst = _sql.connect(str(target))
                with dst:
                    src.backup(dst)
                src.close()
                dst.close()
                # Чистим старше 7 дней
                cutoff = time.time() - 7 * 86400
                for f in backup_dir.glob("tasks-*.db"):
                    if f.stat().st_mtime < cutoff:
                        f.unlink()
                log.info("backup: %s", target.name)
            except Exception as exc:  # noqa: BLE001
                log.warning("backup failed: %s", exc)

    t = Thread(target=loop, daemon=True, name="backup-loop")
    t.start()


import re as _re

# Hex-id паттерн: 12 символов (полный) или #6+ (упоминание)
_TASK_ID_RE = _re.compile(r"\b([a-f0-9]{12})\b|#([a-f0-9]{6,12})\b")


def _extract_task_ids(text: str, known_prefixes: set[str]) -> set[str]:
    """Из текста промта Task tool вытаскиваем все task_id, существующие в БД."""
    if not text:
        return set()
    out = set()
    for m in _TASK_ID_RE.finditer(text):
        cand = m.group(1) or m.group(2)
        if not cand:
            continue
        # Полные 12-символьные — проверяем точно. Короткие — по префиксу.
        if len(cand) == 12 and cand in known_prefixes:
            out.add(cand)
        elif len(cand) >= 6:
            for full in known_prefixes:
                if full.startswith(cand):
                    out.add(full)
                    break
    return out


def _auto_restore_delegated_tasks(delegated_ids: set[str]) -> None:
    """После конца сессии тимлида: для каждого id который он делегировал через
    Task tool, если он ещё в todo/wip — автоматически перевожу в review.

    Это safety-net: тимлид НЕ должен забывать update_task, но в реальности
    забывает. Лучше авто-закрыть и попросить пользователя acceptance, чем
    оставить «висящую» работу.
    """
    if not delegated_ids:
        return
    try:
        restored = []
        conn = db._connect(DB_PATH)  # type: ignore
        try:
            for tid in delegated_ids:
                row = conn.execute(
                    "SELECT id, status, assignee, title FROM tasks WHERE id = ?",
                    (tid,),
                ).fetchone()
                if not row:
                    continue
                if row["status"] not in ("todo", "wip"):
                    continue
                if row["assignee"] in ("пользователь", None):
                    continue
                restored.append({
                    "id": row["id"],
                    "title": row["title"],
                    "assignee": row["assignee"],
                    "was": row["status"],
                })
        finally:
            conn.close()

        if not restored:
            return

        # Переводим в review + коммент через MCP-tools (надёжнее чем прямой SQL)
        from devboard_tasks import tools as pt_tools
        for r in restored:
            pt_tools.update_task(r["id"], status="review", db_path=DB_PATH)
            pt_tools.add_comment(
                r["id"], "тимлид",
                "🛠 Auto-restored backend safety-net: задача делегирована через "
                "Task tool но не была переведена в review. Перевожу автоматически. "
                "Пользователь: проверь артефакты и accept или верни в work.",
                db_path=DB_PATH,
            )

        # System-сообщение в чат
        lines = [f"  • #{r['id'][:6]} ({r['assignee']}, было {r['was']}) — {r['title'][:55]}"
                 for r in restored[:10]]
        text = (
            f"🛠 Safety-net автоматически перевёл в review {len(restored)} "
            f"делегированных подзадач которые тимлид забыл закрыть. "
            f"Проверь артефакты на диске и accept / верни в work:\n\n"
            + "\n".join(lines)
        )
        if len(restored) > 10:
            text += f"\n  ... и ещё {len(restored) - 10}"
        db.post_chat_message(DB_PATH, "system", text)
        log.info("safety-net: автоматически восстановлено %d задач", len(restored))
    except Exception as exc:  # noqa: BLE001
        log.warning("safety-net auto-restore упал: %s", exc)


def _stream_reader(proc: subprocess.Popen, queue: Queue, log_file: Path) -> None:
    """Читает stream-json stdout claude и кладёт события в queue.

    Дополнительно отслеживает каждый Task tool вызов — извлекает task_id из
    prompt'а subagent'а. После завершения сессии safety-net автоматически
    переведёт эти id в review если тимлид забыл сделать update_task.
    """
    assert proc.stdout is not None
    session_started_at = int(time.time())
    # Все id задач существующих в БД на момент старта сессии — для матчинга
    known_ids: set[str] = set()
    try:
        conn = db._connect(DB_PATH)  # type: ignore
        try:
            known_ids = {r["id"] for r in conn.execute("SELECT id FROM tasks")}
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        log.warning("не смог собрать known_ids: %s", exc)

    delegated_ids: set[str] = set()

    with log_file.open("a", encoding="utf-8") as f:
        f.write(f"\n=== STARTED at {session_started_at} ===\n")
        for raw in proc.stdout:
            raw_stripped = raw.rstrip("\n").strip()
            f.write(raw_stripped + "\n")
            f.flush()
            if not raw_stripped:
                continue
            # Парсим JSON-событие — ловим Task tool delegations
            if raw_stripped.startswith("{"):
                try:
                    ev = json.loads(raw_stripped)
                    if ev.get("type") == "assistant":
                        for block in ev.get("message", {}).get("content", []):
                            if block.get("type") == "tool_use" and block.get("name") == "Task":
                                prompt = block.get("input", {}).get("prompt", "")
                                ids = _extract_task_ids(prompt, known_ids)
                                if ids:
                                    delegated_ids.update(ids)
                                    log.info("safety-net: запомнил делегирование Task → %s", ids)
                except (json.JSONDecodeError, KeyError):
                    pass

            human = _format_stream_event(raw_stripped)
            ts = time.strftime("%H:%M:%S")
            queue.put({"ts": ts, "human": human, "raw": raw_stripped})
        queue.put({"ts": time.strftime("%H:%M:%S"),
                   "human": "✓ Сессия завершена",
                   "raw": "[--- session ended ---]"})
    # После полного завершения сессии — авто-восстановление статусов
    _auto_restore_delegated_tasks(delegated_ids)


def _has_pending_work(dept_id: str = "dev") -> bool:
    """Есть ли задачи в очереди лида отдела? (todo + wip + needs_approval кроме destructive).

    dept_id — идентификатор отдела; assignee определяется через _find_lead_for_department.
    Fallback: dept_id='dev' → assignee='тимлид' (обратная совместимость).
    """
    assignee = _find_lead_for_department(DB_PATH, dept_id) or "тимлид"
    try:
        for status in ("todo", "wip"):
            tasks = db.list_tasks(DB_PATH, status=status, assignee=assignee, limit=20)
            if tasks:
                return True
        # needs_approval с assignee=лид (approved task ждут разморозки)
        approval_tasks = db.list_tasks(DB_PATH, status="needs_approval", assignee=assignee, limit=20)
        if approval_tasks:
            return True
    except Exception as exc:  # noqa: BLE001
        log.warning("auto: ошибка при проверке очереди: %s", exc)
    return False


def _auto_can_start(now: int) -> tuple[bool, str]:
    """Можно ли сейчас запустить авто-сессию? (bool, reason)."""
    if not _team_state["auto_mode"]:
        return False, "авто-режим выключен"
    proc = _team_state["process"]
    if proc is not None and proc.poll() is None:
        return False, "сессия уже работает"
    # S17.3: ждём завершения _stream_reader предыдущей сессии прежде чем
    # стартовать новую. _stream_reader может удерживать SQLite write-lock
    # через _auto_restore_delegated_tasks — если новый MCP-сервер попытается
    # открыть tasks.db пока лок занят, он не сможет инициализироваться и
    # claude упадёт с is_error=1 через 90 секунд (HTTP timeout).
    reader = _team_state.get("reader_thread")
    if reader is not None and reader.is_alive():
        return False, "предыдущий reader_thread ещё жив (cleanup)"
    history = _team_state["starts_history"]
    # Чистим старше часа
    cutoff = now - 3600
    history[:] = [t for t in history if t >= cutoff]
    if history:
        since_last = now - history[-1]
        if since_last < _AUTO_MIN_INTERVAL_SEC:
            return False, f"слишком часто (последний запуск {since_last}с назад, минимум {_AUTO_MIN_INTERVAL_SEC}с)"
    if len(history) >= _AUTO_MAX_PER_HOUR:
        return False, f"лимит {_AUTO_MAX_PER_HOUR} сессий в час исчерпан"
    if not _has_pending_work():
        return False, "очередь тимлида пустая"
    return True, "ок"


def _auto_monitor_loop() -> None:
    """Фоновый поток: следит за завершением сессии и запускает следующую если в авто-режиме."""
    log.info("auto-monitor: запущен")
    while True:
        time.sleep(_AUTO_CHECK_INTERVAL_SEC)
        try:
            now = int(time.time())
            ok, reason = _auto_can_start(now)
            if ok:
                log.info("auto-monitor: запускаю следующую сессию")
                _team_state["auto_pause_reason"] = None
                res = _start_team_process(triggered_by="auto")
                if not res.get("ok"):
                    _team_state["auto_pause_reason"] = res.get("reason", "не запустился")
            else:
                _team_state["auto_pause_reason"] = reason if _team_state["auto_mode"] else None
        except Exception as exc:  # noqa: BLE001
            log.warning("auto-monitor: исключение: %s", exc)


def _smart_default_role(db_path: "Path | None" = None) -> str:
    """Smart-default для кнопки «Запустить» без явного выбора роли.

    Phase 1.7 fix: раньше JS hardcoded "managing-director" → запускался Управляющий,
    игнорируя haiku-задачи дев-команды. Теперь:

    - Если есть todo задачи с assignee=*-lead → запускаем lead с самой свежей задачи.
    - Если есть todo задачи на специалистов (без lead) → запускаем lead их отдела.
    - Иначе → managing-director (координатор).

    Returns:
        slug роли для запуска.
    """
    from devboard_tasks import db as _db_mod
    path = db_path or DB_PATH
    try:
        all_todo = _db_mod.list_tasks(path, status="todo", limit=500)
    except Exception:
        return "managing-director"
    if not all_todo:
        return "managing-director"

    # 1. Lead-задачи с самой свежей датой.
    lead_tasks = [t for t in all_todo
                  if (t.get("assignee") or "").endswith("-lead")]
    if lead_tasks:
        latest = max(lead_tasks, key=lambda x: x.get("created_at", 0))
        return latest["assignee"]

    # 2. Задача на специалиста → определить lead его отдела.
    for t in sorted(all_todo, key=lambda x: x.get("created_at", 0), reverse=True):
        dept_id = t.get("department_id")
        if not dept_id:
            continue
        try:
            lead_name = _find_lead_for_department(path, dept_id)
            if lead_name:
                return lead_name
        except Exception:
            continue

    # 3. Никого не нашли — запускаем Управляющего.
    return "managing-director"


def pick_model_for_role(role: str, db_path: "Path | None" = None) -> str:
    """Выбрать alias модели (haiku/sonnet/opus) для роли по её очереди задач.

    B5 (1.6): Фильтрует задачи очереди роли (assignee=role, status=todo),
    применяет router.pick() — максимальный model_hint wins.

    Returns:
        alias модели: 'haiku' | 'sonnet' | 'opus'
    """
    from devboard_tasks import db as _db_mod, router as _router_mod  # local import — не тяжело

    path = db_path or DB_PATH
    # Берём только todo-задачи этой роли — именно они определяют следующую сессию
    role_tasks = _db_mod.list_tasks(path, status="todo", assignee=role, limit=200)
    decision = _router_mod.pick(role_tasks)
    return decision["model_alias"]


def build_claude_command(
    role: str,
    *,
    db_path: "Path | None" = None,
    commands_dir: "Path | None" = None,
) -> "tuple[list[str], dict[str, str], Path]":
    """Построить (cmd, extra_env) для запуска subprocess тимлида.

    B5 (1.6): Определяет модель через pick_model_for_role() и записывает
    DEVBOARD_TEAM_MODEL в extra_env — devboard-work.sh подхватит её и пропустит
    внутренний роутер, запустив claude с нужной --model.

    Returns:
        (cmd, extra_env) — список аргументов и словарь доп. переменных окружения.
    """
    _cmds = commands_dir or _COMMANDS_DIR

    if role == "managing-director":
        if sys.platform == "win32":
            work_script = _cmds / "devboard-managing.ps1"
            cmd: list[str] = [
                "powershell",
                "-ExecutionPolicy",
                "Bypass",
                "-NoProfile",
                "-File",
                str(work_script),
            ]
        else:
            work_script = _cmds / "devboard-managing.sh"
            cmd = ["/bin/bash", str(work_script)]
    else:
        if sys.platform == "win32":
            work_script = _cmds / "devboard-work.ps1"
            cmd = [
                "powershell",
                "-ExecutionPolicy",
                "Bypass",
                "-NoProfile",
                "-File",
                str(work_script),
                "--role",
                role,
            ]
        else:
            work_script = _cmds / "devboard-work.sh"
            cmd = ["/bin/bash", str(work_script), "--role", role]

    # B5 (1.6): Определяем модель по hint-очереди роли и форсируем через env-var.
    # devboard-work.sh (строки 125-128) читает DEVBOARD_TEAM_MODEL и пропускает
    # встроенный роутер — claude получает --model с нужным значением.
    model_alias = pick_model_for_role(role, db_path=db_path)
    extra_env: dict[str, str] = {
        "DEVBOARD_TASKS_DB": str(db_path or DB_PATH),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "DEVBOARD_TEAM_MODEL": model_alias,
    }

    return cmd, extra_env, work_script


def _start_team_process(triggered_by: str = "user", role: str = "managing-director") -> dict[str, Any]:
    """Запустить subprocess тимлида.

    Выбор скрипта зависит от роли (role):
      - 'managing-director' → devboard-managing.sh (или .ps1 на Windows)
      - остальные роли → devboard-work.sh --role <role> (или .ps1 --role <role>)

    Выбор платформы: на Windows — .ps1 через powershell,
    на macOS/Linux — .sh через bash.

    B5 (1.6): модель определяется через build_claude_command() / pick_model_for_role()
    по model_hint задач в очереди роли и инжектируется через DEVBOARD_TEAM_MODEL env-var.
    """

    with _team_state["lock"]:
        proc = _team_state["process"]
        if proc is not None and proc.poll() is None:
            return {"ok": False, "reason": "already_running", "pid": proc.pid}

        cmd, extra_env, work_script = build_claude_command(role)

        if not work_script.exists():
            return {"ok": False, "reason": "missing_script", "path": str(work_script)}

        new_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=str(_REPO_ROOT),
            env={
                **os.environ,
                **extra_env,
            },
        )
        _team_state["process"] = new_proc
        now = int(time.time())
        _team_state["started_at"] = now
        _team_state["starts_history"].append(now)
        _PID_FILE.write_text(str(new_proc.pid))
        log.info("team session started (triggered_by=%s, pid=%d)", triggered_by, new_proc.pid)
        # Чистим очередь
        while not _team_state["queue"].empty():
            try:
                _team_state["queue"].get_nowait()
            except Empty:
                break
        # Поток-читатель
        t = Thread(
            target=_stream_reader,
            args=(new_proc, _team_state["queue"], _LIVE_LOG),
            daemon=True,
            name=f"stream-reader-{new_proc.pid}",
        )
        t.start()
        _team_state["reader_thread"] = t  # S17.3: отслеживаем для auto_can_start
        return {"ok": True, "pid": new_proc.pid}


def _stop_team_process() -> dict[str, Any]:
    with _team_state["lock"]:
        proc = _team_state["process"]
        if proc is None or proc.poll() is not None:
            return {"ok": False, "reason": "not_running"}
        # Windows не понимает SIGTERM для не-консольного дочернего процесса;
        # используем terminate() — он шлёт CTRL_BREAK_EVENT либо TerminateProcess.
        if sys.platform == "win32":
            proc.terminate()
        else:
            proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        _team_state["process"] = None
        if _PID_FILE.exists():
            _PID_FILE.unlink()
        return {"ok": True}


def _team_status() -> dict[str, Any]:
    proc = _team_state["process"]
    if proc is None or proc.poll() is not None:
        return {"status": "stopped"}
    return {
        "status": "running",
        "pid": proc.pid,
        "started_at": _team_state["started_at"],
    }


# === Inter-department helpers (S11.1, ADR-005) ===

# Сортировка задач в очереди отдела: сначала по приоритету (P0<P1<P2<P3), потом по created_at.
_PRIORITY_RANK: dict[str, int] = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
# Статусы которые считаются «в очереди» для capacity hint.
_QUEUE_STATUSES = ("todo", "wip", "needs_approval")


def _is_lead_role_slug(role_slug: str, requester_dept_id: str) -> bool:
    """Проверяет что role_slug — это Lead отдела requester_dept_id или owner.

    Принимаем (ADR-005 §2.2 + legacy):
      - owner / пользователь          — глобальный owner
      - <dept>-lead                    — формат v2.0 (marketing-lead, design-lead)
      - тимлид                         — legacy v1.x dev-команда
      - тимлид-<dept> / lead-<dept>    — на всякий случай альтернативный формат
    """
    if not role_slug:
        return False
    s = role_slug.strip().lower()
    if s in ("owner", "пользователь"):
        return True
    # Legacy v1: dev-команда, тимлид. Считаем валидным только если requester=dev.
    if s == "тимлид" and requester_dept_id == "dev":
        return True
    dept = requester_dept_id.lower()
    if s == f"{dept}-lead":
        return True
    if s in (f"тимлид-{dept}", f"lead-{dept}"):
        return True
    return False


def _find_lead_for_department(db_path: Path, dept_id: str) -> Optional[str]:
    """Ищет slug Lead-роли указанного отдела (для проставления assignee inter-task'у).

    Возвращает name роли, у которой department_id=dept_id и name заканчивается на '-lead'.
    Для legacy 'dev' — возвращает 'тимлид'. None если не нашли.
    """
    if dept_id == "dev":
        return "тимлид"
    conn = db._connect(db_path)
    try:
        row = conn.execute(
            "SELECT name FROM roles WHERE department_id = ? AND name LIKE '%-lead' LIMIT 1",
            (dept_id,),
        ).fetchone()
        if row is not None:
            return row["name"]
        return None
    finally:
        conn.close()


def _compute_queue_position(
    db_path: Path, dept_id: str, task_id: str
) -> tuple[Optional[int], int]:
    """Возвращает (position, total) задачи task_id в очереди отдела dept_id.

    position — 1-based индекс. None если task_id нет в очереди отдела.
    total — общее число задач в очереди (status in _QUEUE_STATUSES).
    Сортировка: priority (P0<P1<P2<P3), затем created_at ASC.
    """
    conn = db._connect(db_path)
    try:
        placeholders = ",".join("?" * len(_QUEUE_STATUSES))
        rows = conn.execute(
            f"SELECT rowid AS _rowid, id, priority, created_at FROM tasks "
            f"WHERE department_id = ? AND status IN ({placeholders})",
            (dept_id, *_QUEUE_STATUSES),
        ).fetchall()
        # Сортируем по (priority_rank, created_at, rowid) — rowid даёт
        # детерминированный порядок вставки при равных created_at (секундная
        # гранулярность). UUID id для tie-break псевдослучаен и делает тест flaky.
        items = sorted(
            rows,
            key=lambda r: (
                _PRIORITY_RANK.get(r["priority"], 99),
                r["created_at"],
                r["_rowid"],
            ),
        )
        total = len(items)
        position: Optional[int] = None
        for idx, r in enumerate(items, start=1):
            if r["id"] == task_id:
                position = idx
                break
        return position, total
    finally:
        conn.close()


def _preview_queue_position(
    db_path: Path, dept_id: str, priority: str
) -> tuple[int, int]:
    """Предсказывает позицию ещё-несозданной задачи с приоритетом priority.

    Возвращает (position, total_after_insert).
    """
    rank = _PRIORITY_RANK.get(priority.upper(), 99)
    conn = db._connect(db_path)
    try:
        placeholders = ",".join("?" * len(_QUEUE_STATUSES))
        rows = conn.execute(
            f"SELECT priority, created_at FROM tasks "
            f"WHERE department_id = ? AND status IN ({placeholders})",
            (dept_id, *_QUEUE_STATUSES),
        ).fetchall()
        # Считаем сколько задач сейчас стоят впереди (с лучшим/равным приоритетом).
        # Новая задача будет ПОСЛЕ всех уже существующих с приоритетом <= rank
        # (т.к. она только что создаётся; для одинакового priority created_at новой больше).
        ahead = sum(1 for r in rows if _PRIORITY_RANK.get(r["priority"], 99) <= rank)
        total = len(rows) + 1
        position = ahead + 1
        return position, total
    finally:
        conn.close()


# === ADR list (для /api/manager/bootstrap) ===

_ADR_DIR = _REPO_ROOT / "docs" / "adr"


def _parse_adr_file(path: Path) -> Optional[dict[str, Any]]:
    """Вытащить {number, title, status, file} из docs/adr/NNNN-*.md.

    Формат файлов (см. 0001..0009): первая строка `# ADR-NNN — Title`,
    далее `- **Status:** XXX (date)`. YAML-frontmatter в наших ADR нет —
    парсим H1 и строку Status построчно. None если файл не похож на ADR.
    """
    try:
        # Читаем только первые ~40 строк — Status обычно в первых 10
        with path.open("r", encoding="utf-8") as f:
            head_lines = [next(f, "") for _ in range(40)]
    except OSError:
        return None

    number: Optional[int] = None
    title: Optional[str] = None
    status: Optional[str] = None

    # Имя файла: 0007-memory-layer.md → number=7
    name = path.name
    if len(name) >= 4 and name[:4].isdigit():
        try:
            number = int(name[:4])
        except ValueError:
            number = None

    h1_re = _re.compile(r"^#\s*ADR-(\d+)\s*[—\-:]\s*(.+?)\s*$")
    status_re = _re.compile(r"^\s*[-*]?\s*\*\*Status:?\*\*\s*[:\-]?\s*(.+?)\s*$", _re.IGNORECASE)

    for raw in head_lines:
        line = raw.rstrip("\n")
        if title is None:
            m = h1_re.match(line)
            if m:
                if number is None:
                    try:
                        number = int(m.group(1))
                    except ValueError:
                        number = None
                title = m.group(2).strip()
                continue
            # fallback: первая H1 без формата ADR-NNN
            if line.startswith("# ") and not line.startswith("## "):
                title = line.lstrip("# ").strip()
        if status is None:
            m = status_re.match(line)
            if m:
                status = m.group(1).strip()
        if title is not None and status is not None:
            break

    if title is None and number is None:
        return None

    return {
        "number": number,
        "title": title,
        "status": status,
        "file": name,
    }


def _list_adr_files(adr_dir: Path = _ADR_DIR) -> list[dict[str, Any]]:
    """Список всех ADR в docs/adr/*.md, отсортирован по номеру."""
    if not adr_dir.exists() or not adr_dir.is_dir():
        return []
    result: list[dict[str, Any]] = []
    for p in sorted(adr_dir.glob("*.md")):
        parsed = _parse_adr_file(p)
        if parsed is not None:
            result.append(parsed)
    # Стабильная сортировка: по number (None — в конец), затем по file
    result.sort(key=lambda x: (x["number"] is None, x["number"] or 0, x["file"]))
    return result


# === Flask app ===


def create_app(db_path: Optional[Path] = None) -> Flask:
    """Фабрика приложения. db_path можно переопределить в тестах."""

    app = Flask(
        __name__,
        template_folder=str(Path(__file__).resolve().parent / "templates"),
        static_folder=str(Path(__file__).resolve().parent / "static"),
    )
    effective_db = Path(db_path) if db_path else DB_PATH
    db.init_db(effective_db)
    app.config["DB_PATH"] = effective_db
    # Авто-перезагрузка шаблонов и статики — чтобы правки HTML/CSS/JS
    # подхватывались без перезапуска процесса.
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.jinja_env.auto_reload = True
    # Кэш статики (CSS/JS) — по умолчанию Flask отдаёт max-age=43200 (12ч).
    # На localhost это вредно: правка app.js не видна пока не очистишь кэш.
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

    @app.after_request
    def _no_cache(resp):
        if request.path.startswith("/static/") or request.path == "/":
            resp.headers["Cache-Control"] = "no-store, must-revalidate"
            resp.headers["Pragma"] = "no-cache"
        return resp
    # Поток бекапа только в production-режиме (НЕ в тестах с tmp-path)
    if db_path is None and not app.config.get("TESTING"):
        _start_backup_thread(effective_db)
        # Auto-режим: фоновый монитор запускает следующую сессию по графу зависимостей
        Thread(target=_auto_monitor_loop, daemon=True, name="auto-monitor").start()

    def _db() -> Path:
        return app.config["DB_PATH"]

    # === HTML ===

    @app.get("/")
    def index() -> str:
        return render_template("kanban.html")

    @app.get("/docs/<path:filename>")
    def serve_docs(filename: str) -> Any:
        """Serve markdown documentation files from /docs directory."""
        from flask import send_from_directory
        docs_dir = _REPO_ROOT / "docs"
        # Security: only allow .md files and prevent directory traversal
        if not filename.endswith(".md") or ".." in filename:
            return "Not found", 404
        file_path = docs_dir / filename
        if not file_path.exists() or not file_path.is_file():
            return "Not found", 404
        # Serve as HTML (markdown) with proper content-type
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        # Convert markdown to HTML (basic: wrap in <pre> and escape)
        from html import escape
        html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{filename}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; max-width: 1000px; margin: 0 auto; padding: 20px; line-height: 1.6; }}
        pre {{ background: #f5f5f5; padding: 15px; overflow-x: auto; border-radius: 5px; }}
        code {{ font-family: "Courier New", monospace; }}
        h1, h2, h3 {{ margin-top: 30px; }}
        table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
        td, th {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
        th {{ background: #f9f9f9; }}
        a {{ color: #0066cc; text-decoration: none; }} a:hover {{ text-decoration: underline; }}
        blockquote {{ border-left: 4px solid #ddd; padding-left: 20px; margin: 20px 0; color: #666; }}
    </style>
</head>
<body>
    <article style="color: #333;">
        <pre>{escape(content)}</pre>
    </article>
</body>
</html>"""
        return html, 200, {"Content-Type": "text/html; charset=utf-8"}

    # === Departments ===

    @app.get("/api/departments")
    def api_list_departments() -> Any:
        """Список активных отделов с counts задач."""
        import re as _re_slug
        depts = db.list_departments(_db())
        result = []
        for d in depts:
            result.append({
                "id": d["id"],
                "name": d["name"],
                "description": d["description"],
                "icon": d["icon"],
                "counts": {
                    "open": d.get("tasks_open", 0),
                    "wip": 0,   # placeholder — tasks_open covers todo+wip
                    "total": d.get("tasks_total", 0),
                },
            })
        return jsonify({"departments": result})

    @app.get("/api/departments/<dept_id>")
    def api_get_department(dept_id: str) -> Any:
        """Детали одного отдела. 404 если не найден.

        S11.1 (ADR-005): при ?task_id=<id> добавляет capacity hint:
          - queue_position: int (1-based позиция задачи в очереди отдела по
            приоритету+created_at; считает только status in ('todo','wip','needs_approval')).
          - queue_total:    int (всего задач в очереди отдела).
        Если task_id не найден или не принадлежит отделу → queue_position=null.
        """
        dept = db.get_department(_db(), dept_id)
        if dept is None:
            return jsonify({"статус": "not_found", "status": "not_found"}), 404

        task_id = request.args.get("task_id")
        if task_id:
            position, total = _compute_queue_position(_db(), dept_id, task_id)
            dept["queue_position"] = position
            dept["queue_total"] = total
        return jsonify({"department": dept})

    @app.get("/api/departments/<dept_id>/queue-position")
    def api_queue_position_preview(dept_id: str) -> Any:
        """S11.1 (ADR-005): preview позиции в очереди для новой задачи.

        Параметры:
          - priority (query, default P3): приоритет создаваемой задачи.

        Возвращает {position, total} — где position это «будет N-м в очереди».
        Используется фронтом перед submit cross-task. 404 если отдела нет.
        """
        if db.get_department(_db(), dept_id) is None:
            return jsonify({"статус": "not_found", "status": "not_found"}), 404
        priority = request.args.get("priority", "P3")
        position, total = _preview_queue_position(_db(), dept_id, priority)
        return jsonify({"position": position, "total": total})

    @app.get("/api/departments/<dept_id>/roles")
    def api_get_department_roles(dept_id: str) -> Any:
        """F1 (1.7): Список ролей отдела для dropdown assignee.

        Возвращает JSON с массивом ролей:
          - lead: { name, description } — лид отдела (роль заканчивается на '-lead')
          - specialists: [{ name, description }, ...] — остальные роли в алфавитном порядке

        404 если отдела нет.
        """
        dept = db.get_department(_db(), dept_id)
        if dept is None:
            return jsonify({"статус": "not_found", "status": "not_found"}), 404

        roles = dept.get("roles", [])

        # Разделяем лида и специалистов
        lead_role = None
        specialist_roles = []

        for role in roles:
            if role["name"].endswith("-lead"):
                lead_role = role
            else:
                specialist_roles.append(role)

        # Сортируем специалистов по имени (алфавитный порядок)
        specialist_roles.sort(key=lambda r: r["name"])

        result = {
            "lead": lead_role,
            "specialists": specialist_roles,
        }
        return jsonify(result)

    @app.post("/api/departments")
    def api_create_department() -> Any:
        """Создание отдела. Валидация: name уникальное, id = slug из name. 409 если уже есть.

        ADR-009 fast-path: если body содержит `template_id` оканчивающийся на '-v2',
        читаем templates/departments/<template_id>.yaml, создаём отдел И все его
        роли (с инжекцией SKILL.md из vendored через inherits_skills mechanism).
        См. §2.5, §2.7.1.
        """
        import re as _re_slug2
        data = request.get_json(silent=True) or {}
        template_id = data.get("template_id")

        # === ADR-009 fast-path: -v2 шаблоны ===
        if isinstance(template_id, str) and template_id.endswith("-v2"):
            return _create_department_from_v2_template(template_id)

        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"статус": "error", "status": "error", "причина": "name обязателен", "reason": "name обязателен"}), 400

        # Генерируем id-slug из name: строчные, пробелы → '-', оставляем [a-z0-9-]
        slug = _re_slug2.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        if not slug:
            return jsonify({"статус": "error", "status": "error", "причина": "name не допускает slug", "reason": "name не допускает slug"}), 400

        description = (data.get("description") or "").strip()
        icon = (data.get("icon") or "🗂").strip() or "🗂"

        try:
            dept = db.create_department(
                _db(),
                dept_id=slug,
                name=name,
                description=description,
                template_id=template_id,
                icon=icon,
            )
        except ValueError as exc:
            return jsonify({"статус": "error", "status": "error", "причина": str(exc), "reason": str(exc)}), 409

        return jsonify({"department": dept}), 201

    def _create_department_from_v2_template(template_id: str) -> Any:
        """ADR-009 §2.5 / §2.7.1 fast-path: создать отдел из v2-шаблона.

        Шаги:
          1. Открыть templates/departments/<template_id>.yaml (404 если нет).
          2. Извлечь dept_slug = template_id без суффикса '-v2'.
          3. Создать запись в `departments`.
          4. Для каждой роли — собрать system_prompt через
             template_loader.load_role_with_inherits() (читает base + SKILL.md).
          5. Вставить роли в SQL-таблицу `roles` (capabilities JSON содержит
             model/system_prompt/is_lead).

        Ошибки:
          - 404 если YAML не найден.
          - 400 если хоть один SKILL.md отсутствует (список в `missing`).
          - 409 если отдел с таким id/name уже существует.
          - 400 при невалидном YAML.
        """
        # Локальный импорт чтобы не тащить yaml/template_loader в hot-path остальных endpoint'ов.
        import yaml  # type: ignore[import-untyped]
        from devboard_tasks.template_loader import load_role_with_inherits  # noqa: E402

        yaml_path = _TEMPLATES_DIR / f"{template_id}.yaml"
        if not yaml_path.is_file():
            return jsonify({
                "статус": "not_found", "status": "not_found",
                "причина": f"шаблон {template_id} не найден",
                "reason": f"template {template_id} not found",
            }), 404

        try:
            template = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            return jsonify({
                "статус": "error", "status": "error",
                "причина": f"невалидный YAML: {exc}",
                "reason": f"invalid YAML: {exc}",
            }), 400

        if not isinstance(template, dict):
            return jsonify({
                "статус": "error", "status": "error",
                "причина": "YAML должен быть mapping на верхнем уровне",
                "reason": "YAML must be a top-level mapping",
            }), 400

        # dept_slug = template_id без суффикса '-v2'
        dept_slug = template_id[: -len("-v2")]
        dept_name = (template.get("name") or "").strip() or dept_slug.capitalize()
        dept_desc = (template.get("description") or "").strip()
        dept_icon = (template.get("icon") or "🗂").strip() or "🗂"

        roles_list = template.get("roles") or []
        if not isinstance(roles_list, list) or not roles_list:
            return jsonify({
                "статус": "error", "status": "error",
                "причина": "в шаблоне нет ролей",
                "reason": "template has no roles",
            }), 400

        # Соберём system_prompt'ы для всех ролей ДО create_department —
        # если SKILL.md отсутствуют, отвалимся с 400 без частичного создания.
        prepared_roles: list[dict[str, Any]] = []
        missing_all: list[str] = []
        for role in roles_list:
            if not isinstance(role, dict) or not role.get("slug"):
                return jsonify({
                    "статус": "error", "status": "error",
                    "причина": "роль без slug в шаблоне",
                    "reason": "role missing slug in template",
                }), 400
            try:
                system_prompt = load_role_with_inherits(
                    role,
                    dept_slug=dept_slug,
                    vendored_root=_VENDORED_KWP_DIR,
                    roles_root=_ROLES_DIR,
                )
            except ValueError as exc:
                # ValueError несёт список missing — добавим в общий аккумулятор.
                missing_all.append(str(exc))
                continue
            prepared_roles.append({
                "slug": role["slug"],
                "name_ru": role.get("name_ru") or role["slug"],
                "name_en": role.get("name_en") or role["slug"],
                "model": role.get("model") or "claude-sonnet-4-6",
                "is_lead": bool(role.get("is_lead", False)),
                "output_spec": (role.get("output_spec") or "").strip(),
                "system_prompt": system_prompt,
            })

        if missing_all:
            return jsonify({
                "статус": "error", "status": "error",
                "причина": "не все SKILL.md найдены",
                "reason": "missing SKILL.md files",
                "missing": missing_all,
            }), 400

        # Создаём отдел.
        try:
            dept = db.create_department(
                _db(),
                dept_id=dept_slug,
                name=dept_name,
                description=dept_desc,
                template_id=template_id,
                icon=dept_icon,
            )
        except ValueError as exc:
            return jsonify({
                "статус": "error", "status": "error",
                "причина": str(exc), "reason": str(exc),
            }), 409

        # Вставляем роли в SQL.
        created_roles: list[dict[str, Any]] = []
        with db.write_lock(_db()):
            conn = db._connect(_db())
            try:
                conn.execute("BEGIN IMMEDIATE")
                for role in prepared_roles:
                    caps = {
                        "llm": "claude",
                        "model": role["model"],
                        "temperature": 0.3,
                        "max_tokens": 16000,
                        "system_prompt": role["system_prompt"],
                        "is_lead": role["is_lead"],
                        "name_ru": role["name_ru"],
                        "name_en": role["name_en"],
                    }
                    # Description — output_spec (single-line, ≤200 char для UI).
                    one_line = " ".join(role["output_spec"].split())
                    if len(one_line) > 200:
                        one_line = one_line[:197] + "..."
                    if not one_line:
                        one_line = f"{role['name_ru']} в отделе {dept_name}"
                    # name PK — может коллидировать с уже существующей default-ролью.
                    # Для v2-шаблонов используем bare slug (соответствует ADR-009 §2.3).
                    try:
                        conn.execute(
                            "INSERT INTO roles (name, description, capabilities, department_id) "
                            "VALUES (?, ?, ?, ?)",
                            (
                                role["slug"],
                                one_line,
                                json.dumps(caps, ensure_ascii=False),
                                dept_slug,
                            ),
                        )
                    except Exception as exc:
                        conn.execute("ROLLBACK")
                        return jsonify({
                            "статус": "error", "status": "error",
                            "причина": f"не удалось вставить роль {role['slug']}: {exc}",
                            "reason": f"failed to insert role {role['slug']}: {exc}",
                        }), 409
                    created_roles.append({
                        "slug": role["slug"],
                        "name_ru": role["name_ru"],
                        "model": role["model"],
                        "is_lead": role["is_lead"],
                        "system_prompt_len": len(role["system_prompt"]),
                    })
                conn.execute("COMMIT")
            finally:
                conn.close()

        return jsonify({
            "department": dept,
            "roles": created_roles,
            "template_id": template_id,
        }), 201

    @app.patch("/api/departments/<dept_id>/archive")
    def api_archive_department(dept_id: str) -> Any:
        """Soft-archive отдела. 403 если dept_id == 'dev'. 404 если не найден."""
        if dept_id == "dev":
            return jsonify({
                "статус": "error",
                "status": "error",
                "причина": "нельзя архивировать default отдел 'dev'",
                "reason": "cannot archive default department 'dev'",
            }), 403

        dept = db.get_department(_db(), dept_id)
        if dept is None:
            return jsonify({"статус": "not_found", "status": "not_found"}), 404

        now = int(time.time())
        with db.write_lock(_db()):
            conn = db._connect(_db())
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "UPDATE departments SET archived_at = ? WHERE id = ?",
                    (now, dept_id),
                )
                conn.execute("COMMIT")
                row = conn.execute(
                    "SELECT * FROM departments WHERE id = ?", (dept_id,)
                ).fetchone()
            finally:
                conn.close()

        return jsonify({
            "department": {
                "id": row["id"],
                "name": row["name"],
                "archived_at": row["archived_at"],
            }
        })

    # === Inter-department (S11.1, ADR-005) ===

    @app.post("/api/departments/<target_id>/tasks")
    def api_create_inter_department_task(target_id: str) -> Any:
        """Создание inter-department task (ADR-005 §2.2).

        Body (JSON):
          - title: str (обязательно)
          - description: str (опц.)
          - priority: P1|P2|P3 (default P3)
          - labels: list[str] (опц.) — наличие 'destructive' → needs_approval
          - requester_department_id: str (обязательно) — id отдела-заказчика
          - requester_role_slug: str (обязательно) — slug Lead отдела A (или owner)

        Pipeline:
          1) Target dept существует и не архивирован → иначе 404 / 410.
          2) requester_department_id существует.
          3) requester_role_slug — Lead отдела A или owner → иначе 403.
          4) Escalation gate:
             - priority in (P1, P2) ИЛИ 'destructive' in labels →
                 status='needs_approval', requires_approval=true, assignee='пользователь'
             - priority='P3' → status='todo', assignee=<target_dept>-lead (если нет — None,
                               задача попадёт в общую очередь target отдела)
          5) INSERT в tasks с department_id=target, requester_department_id, requester_role_slug.
          6) Audit-сообщение в global inter-department channel (chat_messages.department_id=NULL).
        """
        data = request.get_json(silent=True) or {}
        title = (data.get("title") or "").strip()
        if not title:
            return jsonify({
                "статус": "error", "status": "error",
                "причина": "title обязателен", "reason": "title is required",
            }), 400

        requester_dept = (data.get("requester_department_id") or "").strip()
        if not requester_dept:
            return jsonify({
                "статус": "error", "status": "error",
                "причина": "requester_department_id обязателен",
                "reason": "requester_department_id is required",
            }), 400

        requester_role = (data.get("requester_role_slug") or "").strip()
        if not requester_role:
            return jsonify({
                "статус": "error", "status": "error",
                "причина": "requester_role_slug обязателен",
                "reason": "requester_role_slug is required",
            }), 400

        # 1. target dept существует и не архивирован
        target = db.get_department(_db(), target_id)
        if target is None:
            return jsonify({"статус": "not_found", "status": "not_found"}), 404
        if target.get("archived_at"):
            return jsonify({
                "статус": "error", "status": "error",
                "причина": "target department архивирован",
                "reason": "target department is archived",
            }), 410

        # 2. requester dept существует
        requester = db.get_department(_db(), requester_dept)
        if requester is None:
            return jsonify({
                "статус": "error", "status": "error",
                "причина": f"requester_department_id={requester_dept!r} не существует",
                "reason": f"requester_department_id={requester_dept!r} not found",
            }), 400

        # 3. AuthZ: requester_role_slug — Lead отдела A или owner
        if not _is_lead_role_slug(requester_role, requester_dept):
            return jsonify({
                "статус": "error", "status": "error",
                "причина": (
                    f"только Lead отдела {requester_dept!r} или owner может создавать "
                    f"inter-department задачи; получено role_slug={requester_role!r}"
                ),
                "reason": "only Lead of requester department or owner can create cross-department tasks",
                "your_role": requester_role,
            }), 403

        # 4. Escalation gate
        priority = (data.get("priority") or "P3").upper()
        labels = list(data.get("labels") or [])
        is_destructive = "destructive" in labels
        is_high_pri = priority in ("P1", "P2")
        if is_high_pri or is_destructive:
            status = "needs_approval"
            requires_approval = True
            # Эскалация owner'у: задача попадает в его Inbox.
            assignee = "пользователь"
        else:
            status = "todo"
            requires_approval = False
            # Назначаем Lead'у target-отдела если можем его найти; иначе None.
            assignee = _find_lead_for_department(_db(), target_id)

        # 5. Insert
        task = db.insert_task(
            _db(),
            title=title,
            description=(data.get("description") or "").strip(),
            assignee=assignee,
            reporter=requester_role,
            priority=priority,
            labels=labels,
            requires_approval=requires_approval,
            status=status,
            department_id=target_id,
            requester_department_id=requester_dept,
            requester_role_slug=requester_role,
        )

        # 6. Audit в global inter-department channel
        try:
            audit_text = (
                f"[{requester_dept} → {target_id}] #{task['id'][:6]} {title!r} ({priority}) — "
                f"created{' (needs_approval)' if requires_approval else ''}"
            )
            db.post_chat_message(_db(), "system", audit_text, department_id=None)
        except Exception as exc:  # noqa: BLE001
            log.warning("inter-department audit log failed: %s", exc)

        return jsonify({"статус": "ok", "задача": task}), 201

    @app.get("/api/chat/inter-department")
    def api_chat_inter_department() -> Any:
        """S11.1 (ADR-005 §2.6): global inter-department channel.

        Это специальный канал — все сообщения с department_id IS NULL.
        Сюда система пишет audit-события cross-task'ов (created / counter / completed).
        Параметры: since (unix-ts), limit (default 100).
        """
        since = int(request.args.get("since", 0))
        limit = int(request.args.get("limit", 100))
        msgs = db.list_chat_messages(_db(), since=since, limit=limit, department_id=None)
        return jsonify({"messages": msgs})

    @app.post("/api/tasks/<task_id>/counter")
    def api_task_counter(task_id: str) -> Any:
        """S11.1 (ADR-005 §2.3): counter-proposal от target Lead.

        Body (JSON):
          - priority: P1|P2|P3 (опц.) — новый приоритет.
          - due_at:   int unix-ts (опц.) — предлагаемый срок.
          - comment:  str — обязательный комментарий (мотивация counter'а).

        Эффект:
          - Если priority задан и валиден — обновляем поле задачи.
          - Если due_at задан — обновляем поле задачи.
          - В историю задачи пишется comment c автором 'system' + меткой counter-proposal.
          - В global inter-department channel пишется audit-запись.
          - В чат отдела-заказчика (department_id=requester_department_id) шлётся notify
            от 'system' — origin Lead увидит.
        404 если задача не найдена. 400 если задача не inter-department (нечего counter'ить).
        """
        data = request.get_json(silent=True) or {}
        comment = (data.get("comment") or "").strip()
        if not comment:
            return jsonify({
                "статус": "error", "status": "error",
                "причина": "comment обязателен", "reason": "comment is required",
            }), 400

        # Читаем задачу
        existing = db.get_task(_db(), task_id)
        if existing is None:
            return jsonify({"статус": "not_found", "status": "not_found"}), 404

        # Проверяем что задача inter-department
        req_dept = existing.get("requester_department_id")
        tgt_dept = existing.get("department_id")
        if not req_dept or req_dept == tgt_dept:
            return jsonify({
                "статус": "error", "status": "error",
                "причина": "задача не inter-department (нечего counter'ить)",
                "reason": "task is not inter-department",
            }), 400

        # Опциональное обновление priority
        update_fields: dict[str, Any] = {}
        new_priority = data.get("priority")
        if new_priority is not None:
            new_priority = str(new_priority).upper()
            from devboard_tasks.models import PRIORITIES
            if new_priority not in PRIORITIES:
                return jsonify({
                    "статус": "error", "status": "error",
                    "причина": f"недопустимый priority={new_priority!r}, ожидалось {PRIORITIES}",
                    "reason": f"invalid priority, expected one of {PRIORITIES}",
                }), 400
            update_fields["priority"] = new_priority

        new_due_at = data.get("due_at")
        if new_due_at is not None:
            try:
                update_fields["due_at"] = int(new_due_at)
            except (TypeError, ValueError):
                return jsonify({
                    "статус": "error", "status": "error",
                    "причина": "due_at должен быть unix-ts (int)",
                    "reason": "due_at must be unix timestamp (int)",
                }), 400

        old_priority = existing.get("priority")
        if update_fields:
            db.update_task(_db(), task_id, **update_fields)

        # Запись в историю задачи
        counter_text = "[counter-proposal] " + comment
        if "priority" in update_fields:
            counter_text += f" | priority {old_priority}→{update_fields['priority']}"
        if "due_at" in update_fields:
            counter_text += f" | due_at→{update_fields['due_at']}"
        db.add_comment(_db(), task_id, "system", counter_text)

        # Audit в global inter-department channel
        try:
            short = task_id[:6]
            audit = (
                f"[{req_dept} → {tgt_dept}] #{short} "
                f"— counter-proposed"
            )
            if "priority" in update_fields:
                audit += f": priority {old_priority}→{update_fields['priority']}"
            db.post_chat_message(_db(), "system", audit, department_id=None)
        except Exception as exc:  # noqa: BLE001
            log.warning("inter-department counter audit log failed: %s", exc)

        # Notify origin (push в отдел-заказчик: department_id=requester_department_id)
        try:
            db.post_chat_message(
                _db(),
                "system",
                f"counter-proposal на задаче #{task_id[:6]}: {comment}",
                department_id=req_dept,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("inter-department counter notify failed: %s", exc)

        # Возвращаем обновлённую задачу
        updated = db.get_task(_db(), task_id)
        return jsonify({"статус": "ok", "задача": updated}), 200

    # === HR pipeline (S10.3, ADR-004 §2.2) ===

    @app.post("/api/hr/start")
    def api_hr_start() -> Any:
        """Старт HR-сессии создания отдела.

        Body (JSON): {name: str, description: str, template_hint?: str}.
        Создаёт запись в hr_sessions (state='hr_planning'), спавнит claude CLI
        subprocess с HR system-prompt. Возвращает {hr_session_id, state}.
        """
        data = request.get_json(silent=True) or {}
        name = (data.get("name") or "").strip()
        description = (data.get("description") or "").strip()
        template_hint = (data.get("template_hint") or "").strip() or None

        if not name:
            return jsonify({
                "статус": "error", "status": "error",
                "причина": "name обязателен", "reason": "name is required",
            }), 400

        try:
            session = db.create_hr_session(
                _db(),
                department_name=name,
                template_hint=template_hint,
                state="hr_planning",
            )
        except ValueError as exc:
            return jsonify({
                "статус": "error", "status": "error",
                "причина": str(exc), "reason": str(exc),
            }), 400

        # Initial message для HR — owner-описание + hint.
        initial_message = description
        if template_hint:
            initial_message += f"\n[template_hint: {template_hint}]"
        if not initial_message:
            initial_message = f"Создай отдел: {name}"

        proc = hr_runner.spawn_hr_subprocess(
            session["id"], initial_message, db_path=_db()
        )
        if proc is None:
            # Spawn упал — переводим сразу в aborted.
            db.update_hr_session(
                _db(), session["id"],
                state="aborted",
                last_message="failed to spawn HR subprocess",
                finished_at=int(time.time()),
            )
            return jsonify({
                "статус": "error", "status": "error",
                "причина": "не удалось запустить HR subprocess",
                "reason": "failed to spawn HR subprocess",
                "hr_session_id": session["id"],
            }), 500

        return jsonify({
            "hr_session_id": session["id"],
            "state": session["state"],
            "department_name": session["department_name"],
        }), 201

    @app.post("/api/hr/answer")
    def api_hr_answer() -> Any:
        """Owner отправляет правки/ответ в активную HR-сессию.

        Body (JSON): {hr_session_id: str, message: str}.
        Спавнит новый HR subprocess с контекстом предыдущего плана и owner-комментом
        через respawn_hr_for_revise (старый stdin-подход заменён — subprocess умирал).
        """
        data = request.get_json(silent=True) or {}
        sid = (data.get("hr_session_id") or "").strip()
        message = (data.get("message") or "").strip()

        if not sid:
            return jsonify({
                "статус": "error", "status": "error",
                "причина": "hr_session_id обязателен",
                "reason": "hr_session_id is required",
            }), 400
        if not message:
            return jsonify({
                "статус": "error", "status": "error",
                "причина": "message обязателен", "reason": "message is required",
            }), 400

        session = db.get_hr_session(_db(), sid)
        if session is None:
            return jsonify({"статус": "not_found", "status": "not_found"}), 404

        # Нельзя отвечать в завершённую сессию.
        if session["state"] in ("active", "aborted"):
            return jsonify({
                "статус": "error", "status": "error",
                "причина": f"hr_session в финальном состоянии {session['state']}",
                "reason": f"session is in final state {session['state']}",
            }), 409

        proc = hr_runner.respawn_hr_for_revise(sid, message, db_path=_db())
        if proc is None:
            return jsonify({
                "статус": "error", "status": "error",
                "причина": "не удалось запустить HR subprocess для revision",
                "reason": "failed to spawn HR subprocess for revision",
            }), 502

        updated = db.get_hr_session(_db(), sid)

        return jsonify({
            "hr_session_id": sid,
            "state": updated["state"],
            "iteration_count": updated["iteration_count"],
        }), 200

    @app.post("/api/hr/approve")
    def api_hr_approve() -> Any:
        """Owner аппрувит план — запускается активация.

        Body (JSON): {hr_session_id: str, plan?: dict}.
        - state → hr_activating
        - валидируем план через validate_hr_plan
        - если invalid: increment attempt_count, при ≥3 → aborted
        - если valid: materialize_roles + create_department в БД → state=active

        План берётся либо из body.plan (если HR/UI передаёт явно), либо из
        session.plan (если HR ранее запостил его).
        """
        data = request.get_json(silent=True) or {}
        sid = (data.get("hr_session_id") or "").strip()
        if not sid:
            return jsonify({
                "статус": "error", "status": "error",
                "причина": "hr_session_id обязателен",
                "reason": "hr_session_id is required",
            }), 400

        session = db.get_hr_session(_db(), sid)
        if session is None:
            return jsonify({"статус": "not_found", "status": "not_found"}), 404

        if session["state"] in ("active", "aborted"):
            return jsonify({
                "статус": "error", "status": "error",
                "причина": f"hr_session в финальном состоянии {session['state']}",
                "reason": f"session is in final state {session['state']}",
            }), 409

        plan = data.get("plan")
        if plan is None:
            plan = session.get("plan")

        if not isinstance(plan, dict):
            return jsonify({
                "статус": "error", "status": "error",
                "причина": "plan отсутствует или невалиден",
                "reason": "plan is missing or invalid",
            }), 400

        # Переводим в hr_activating.
        db.update_hr_session(_db(), sid, state="hr_activating", plan_json=json.dumps(plan, ensure_ascii=False))

        # Валидируем план.
        result = validate_hr_plan(plan)
        if not result.ok:
            new_attempt = session["attempt_count"] + 1
            if new_attempt >= hr_runner.HR_MAX_VALIDATION_ATTEMPTS:
                # Слишком много попыток → aborted.
                db.update_hr_session(
                    _db(), sid,
                    state="aborted",
                    attempt_count=new_attempt,
                    last_message=f"validation failed after {new_attempt} attempts: {'; '.join(result.errors[:5])}",
                    finished_at=int(time.time()),
                )
                hr_runner.close_hr_subprocess(sid)
                return jsonify({
                    "статус": "aborted", "status": "aborted",
                    "причина": "план не прошёл валидацию 3 раза подряд",
                    "reason": "plan failed validation 3 times in a row",
                    "errors": result.errors,
                    "attempts": new_attempt,
                }), 422
            # Иначе — возвращаем ошибки + сбрасываем в hr_revising, HR должен сгенерировать новый план.
            db.update_hr_session(
                _db(), sid,
                state="hr_revising",
                attempt_count=new_attempt,
                last_message="; ".join(result.errors[:5]),
            )
            return jsonify({
                "статус": "invalid_plan", "status": "invalid_plan",
                "errors": result.errors,
                "attempts": new_attempt,
                "max_attempts": hr_runner.HR_MAX_VALIDATION_ATTEMPTS,
            }), 422

        # План валидный → материализуем роли + создаём отдел в БД.
        dept_name = plan.get("department", {}).get("name") or session["department_name"]
        dept_desc = plan.get("department", {}).get("description") or ""
        dept_icon = plan.get("department", {}).get("icon") or "🗂"
        dept_slug = hr_runner.department_slug(dept_name)

        created_files, mat_errors = hr_runner.materialize_roles(plan)
        if mat_errors:
            db.update_hr_session(
                _db(), sid,
                state="aborted",
                last_message=f"materialize failed: {'; '.join(mat_errors)}",
                finished_at=int(time.time()),
            )
            hr_runner.close_hr_subprocess(sid)
            return jsonify({
                "статус": "error", "status": "error",
                "причина": "не удалось записать файлы ролей",
                "reason": "failed to write role files",
                "errors": mat_errors,
            }), 500

        # Создаём department в БД (idempotent если уже есть — добавим суффикс).
        try:
            dept = db.create_department(
                _db(),
                dept_id=dept_slug,
                name=dept_name,
                description=dept_desc,
                template_id=plan.get("template_id"),
                icon=dept_icon,
            )
        except ValueError as exc:
            # Уже есть отдел с таким id/name. Пробуем с суффиксом.
            try:
                dept = db.create_department(
                    _db(),
                    dept_id=f"{dept_slug}-{sid[:6]}",
                    name=f"{dept_name} ({sid[:6]})",
                    description=dept_desc,
                    template_id=plan.get("template_id"),
                    icon=dept_icon,
                )
            except ValueError as exc2:
                # Rollback файлов и aborted.
                for f in created_files:
                    try:
                        f.unlink()
                    except OSError:
                        pass
                db.update_hr_session(
                    _db(), sid,
                    state="aborted",
                    last_message=f"department insert failed: {exc}; {exc2}",
                    finished_at=int(time.time()),
                )
                hr_runner.close_hr_subprocess(sid)
                return jsonify({
                    "статус": "error", "status": "error",
                    "причина": str(exc),
                    "reason": str(exc),
                }), 409

        # Активация успешна.
        db.update_hr_session(
            _db(), sid,
            state="active",
            last_message=f"activated: {dept['id']} ({len(created_files)} roles)",
            finished_at=int(time.time()),
        )
        hr_runner.close_hr_subprocess(sid)

        return jsonify({
            "статус": "ok", "status": "ok",
            "hr_session_id": sid,
            "state": "active",
            "department": dept,
            "roles_created": [str(p) for p in created_files],
        }), 200

    @app.get("/api/hr/status/<session_id>")
    def api_hr_status(session_id: str) -> Any:
        """Текущий state HR-сессии + последний message.

        Возвращает: {hr_session_id, state, department_name, iteration_count,
                     attempt_count, last_message, plan, finished_at}.
        404 если сессия не найдена.
        """
        session = db.get_hr_session(_db(), session_id)
        if session is None:
            return jsonify({"статус": "not_found", "status": "not_found"}), 404
        return jsonify({
            "hr_session_id": session["id"],
            "state": session["state"],
            "department_name": session["department_name"],
            "iteration_count": session["iteration_count"],
            "attempt_count": session["attempt_count"],
            "last_message": session["last_message"],
            "plan": session.get("plan"),
            "started_at": session["started_at"],
            "finished_at": session["finished_at"],
            "template_hint": session["template_hint"],
        }), 200

    # === Tasks ===

    @app.get("/api/tasks")
    def api_list_tasks() -> Any:
        status = request.args.get("status")
        assignee = request.args.get("assignee")
        label = request.args.get("label")
        limit = int(request.args.get("limit", 200))
        include_archived = request.args.get("archived") in ("1", "true", "yes")

        # S8.3: department filter
        # ?department=__all__  → все задачи (no filter); tools.list_tasks(department_id=None)
        # ?department=<id>     → фильтр по department_id
        # не указан            → default 'dev' (backward compat)
        # tools.list_tasks behaviour: department_id=None → _filter=False → all tasks
        #                             department_id=X    → _filter=True  → filter by X
        dept_param = request.args.get("department")
        if dept_param == "__all__":
            dept_id_filter: Optional[str] = None  # no filter
        elif dept_param is not None:
            dept_id_filter = dept_param
        else:
            dept_id_filter = "dev"

        res = tools.list_tasks(
            status=status, assignee=assignee, label=label, limit=limit,
            db_path=_db(),
            department_id=dept_id_filter,
        )
        if res["статус"] != "ok":
            return jsonify(res), 400

        # Архивация: done-задачи старше 7 дней считаются архивными.
        # В основные колонки не идут — фронт показывает их в свёрнутом блоке.
        import time as _t
        cutoff = _t.time() - 7 * 86400
        # Метим задачи флагом _has_deps (для иконки в карточке)
        ids_with_deps = set()
        conn = db._connect(_db())  # type: ignore
        try:
            for (tid,) in conn.execute(
                "SELECT DISTINCT task_id FROM task_dependencies"
            ).fetchall():
                ids_with_deps.add(tid)
            for (tid,) in conn.execute(
                "SELECT DISTINCT depends_on FROM task_dependencies"
            ).fetchall():
                ids_with_deps.add(tid)
        finally:
            conn.close()

        active = []
        archived = []
        for t in res["задачи"]:
            t["_has_deps"] = t["id"] in ids_with_deps
            if (
                t["status"] == "done"
                and t.get("completed_at")
                and t["completed_at"] < cutoff
            ):
                archived.append(t)
            else:
                active.append(t)

        by_status = {s: [] for s in ("todo", "wip", "needs_approval", "review", "done", "blocked")}
        for t in active:
            by_status.setdefault(t["status"], []).append(t)
        result = {
            "задачи": active,
            "колонки": by_status,
            "архив_count": len(archived),
        }
        if include_archived:
            result["архив"] = archived
        return jsonify(result)

    @app.post("/api/tasks")
    def api_create_task() -> Any:
        data = request.get_json(silent=True) or {}
        # ADR-003 §2.4.1 + ADR-009: department_id определяется в порядке:
        # 1) body.department_id (явное указание), 2) X-Department header,
        # 3) cookie current_department, 4) fallback 'dev'.
        department_id = (
            data.get("department_id")
            or request.headers.get("X-Department")
            or request.cookies.get("current_department")
            or "dev"
        )
        res = tools.create_task(
            title=data.get("title", ""),
            description=data.get("description", ""),
            assignee=data.get("assignee"),
            reporter=data.get("reporter", "пользователь"),
            priority=data.get("priority", "P2"),
            parent_id=data.get("parent_id"),
            requires_approval=bool(data.get("requires_approval", False)),
            status=data.get("status", "todo"),
            labels=data.get("labels"),
            model_hint=data.get("model_hint") or None,
            department_id=department_id,
            db_path=_db(),
        )
        if res["статус"] != "ok":
            return jsonify(res), 400
        return jsonify(res), 201

    @app.get("/api/tasks/<task_id>")
    def api_get_task(task_id: str) -> Any:
        res = tools.get_task(task_id, db_path=_db())
        if res["статус"] == "not_found":
            return jsonify(res), 404
        return jsonify(res)

    @app.get("/api/tasks/<task_id>/parsed")
    def api_parse_task(task_id: str) -> Any:
        res = tools.parse_task_description(task_id, db_path=_db())
        if res["статус"] == "not_found":
            return jsonify(res), 404
        if res["статус"] != "ok":
            return jsonify(res), 400
        return jsonify(res)

    @app.patch("/api/tasks/<task_id>")
    def api_update_task(task_id: str) -> Any:
        data = request.get_json(silent=True) or {}
        res = tools.update_task(
            task_id,
            status=data.get("status"),
            assignee=data.get("assignee"),
            title=data.get("title"),
            description=data.get("description"),
            priority=data.get("priority"),
            labels=data.get("labels"),
            requires_approval=data.get("requires_approval"),
            db_path=_db(),
            _bypass_safety_net=True,  # UI-вызов: пользователь может ставить done
        )
        if res["статус"] == "not_found":
            return jsonify(res), 404
        if res["статус"] != "ok":
            return jsonify(res), 400
        return jsonify(res)

    @app.post("/api/tasks/<task_id>/comment")
    def api_comment(task_id: str) -> Any:
        data = request.get_json(silent=True) or {}
        author = data.get("author", "пользователь")
        text = data.get("text", "")
        res = tools.add_comment(task_id, author, text, db_path=_db())
        if res["статус"] == "not_found":
            return jsonify(res), 404
        if res["статус"] != "ok":
            return jsonify(res), 400
        # Зеркалим комментарии пользователя в чат, чтобы тимлид (читающий только
        # chat_recent) их не пропустил. Системные approve/reject не зеркалим
        # — они и так выглядят как «approved at ...» без полезной нагрузки.
        if author == "пользователь":
            stripped = text.strip() if text else ""
            is_system_marker = stripped.startswith("approved at ") or stripped.startswith("REJECTED:")
            if stripped and not is_system_marker:
                try:
                    db.post_chat_message(
                        _db(),
                        "пользователь",
                        f"[коммент к #{task_id[:6]}] {stripped}",
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("не смог зеркалить коммент в чат: %s", exc)
        return jsonify(res), 201

    @app.post("/api/tasks/<task_id>/approve")
    def api_approve(task_id: str) -> Any:
        """Одобрение задачи в needs_approval.

        Workflow по approval_gates.md: subagent создаёт needs_approval-таску
        с assignee=пользователь, ждёт. После approve задача:
          - переходит в status=todo (НЕ wip — wip = «исполнитель уже работает»,
            а тут как раз нужно чтобы новый прогон тимлида взял задачу).
          - assignee — зависит от типа задачи (intra vs cross-task):
              * intra (requester_department_id is None): assignee = reporter
                (создатель задачи), или 'тимлид' если reporter не задан.
                Backward-compat поведение для v1.x.
              * cross-task (requester_department_id is not None, ADR-005):
                assignee = Lead отдела-исполнителя (target = department_id).
                Reporter здесь — заказчик (<dept>-lead), не исполнитель;
                ставить его в assignee неправильно семантически И ломает
                валидацию ROLES в tools.update_task (баг #5933b0f3b933).
                Fallback: если Lead не найден, оставляем 'пользователь'
                (owner оставляет себе для повторного делегирования вручную).
        """
        existing = tools.get_task(task_id, db_path=_db())
        if existing["статус"] == "not_found":
            return jsonify(existing), 404
        task_obj = existing["задача"]
        # S11.1 (ADR-005): cross-task если requester_department_id заполнен.
        requester_dept = task_obj.get("requester_department_id")
        is_cross_task = bool(requester_dept)
        if is_cross_task:
            target_dept = task_obj.get("department_id")
            new_assignee = (
                _find_lead_for_department(_db(), target_dept) if target_dept else None
            )
            if not new_assignee:
                # Lead отдела-исполнителя не найден (например, отдел без Lead-роли
                # либо department_id отсутствует) — owner оставляет задачу себе.
                new_assignee = "пользователь"
        else:
            # Intra-task (legacy v1.x): возвращаем на reporter'а.
            new_assignee = task_obj.get("reporter") or "тимлид"

        # tools.update_task валидирует assignee против фиксированного whitelist
        # ROLES (v1.x). Для cross-task assignee — это динамическая dept-роль
        # (например 'design-lead'), которой нет в whitelist. Обходим: для
        # cross-task используем db.update_task напрямую (UI-путь, аналогично
        # созданию cross-task в api_create_inter_task — там тоже db.insert_task,
        # а не tools.create_task). Для intra-task сохраняем штатный путь через
        # tools.update_task — это даёт нам бесплатный safety-net.
        if is_cross_task:
            updated = db.update_task(
                _db(), task_id, status="todo", assignee=new_assignee
            )
            if updated is None:
                return jsonify({"статус": "not_found", "status": "not_found"}), 404
            upd = {"статус": "ok", "задача": updated}
        else:
            upd = tools.update_task(
                task_id,
                status="todo",
                assignee=new_assignee,
                db_path=_db(),
            )
            if upd["статус"] != "ok":
                return jsonify(upd), 400
        comment_text = (request.get_json(silent=True) or {}).get(
            "text", f"approved at {time.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        tools.add_comment(task_id, "пользователь", comment_text, db_path=_db())
        return jsonify({"статус": "ok", "задача": upd["задача"]})

    @app.post("/api/tasks/<task_id>/reject")
    def api_reject(task_id: str) -> Any:
        upd = tools.update_task(task_id, status="done", db_path=_db(), _bypass_safety_net=True)
        if upd["статус"] == "not_found":
            return jsonify(upd), 404
        if upd["статус"] != "ok":
            return jsonify(upd), 400
        reason = (request.get_json(silent=True) or {}).get(
            "text", f"rejected at {time.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        tools.add_comment(task_id, "пользователь", f"REJECTED: {reason}", db_path=_db())
        return jsonify({"статус": "ok", "задача": upd["задача"]})

    @app.post("/api/tasks/<task_id>/dependencies")
    def api_add_dependency(task_id: str) -> Any:
        data = request.get_json(silent=True) or {}
        depends_on = data.get("depends_on", "")
        if not depends_on:
            return jsonify({"статус": "error", "status": "error", "причина": "depends_on пустой", "reason": "depends_on пустой"}), 400
        res = tools.add_dependency(task_id, depends_on, db_path=_db())
        if res["статус"] != "ok":
            return jsonify(res), 400
        return jsonify(res), 201

    @app.delete("/api/tasks/<task_id>/dependencies/<blocker_id>")
    def api_remove_dependency(task_id: str, blocker_id: str) -> Any:
        res = tools.remove_dependency(task_id, blocker_id, db_path=_db())
        return jsonify(res), 200 if res["статус"] == "ok" else 404

    @app.delete("/api/tasks/<task_id>")
    def api_delete(task_id: str) -> Any:
        deleted = db.delete_task(_db(), task_id)
        if not deleted:
            return jsonify({"статус": "not_found"}), 404
        return jsonify({"статус": "ok"})

    # === Roles ===

    @app.get("/api/roles")
    def api_roles() -> Any:
        """Список ролей.

        S9.2: поддержка ?department=<id>:
          - ?department=__all__ (или отсутствует) → ВСЕ роли (global + per-dept).
          - ?department=<id>                      → только роли отдела <id>
                                                    (включая global, у которых
                                                     department_id IS NULL).

        Поле `department_id` поднимается в верхний уровень результата
        (берётся напрямую из БД, так как tools.list_roles его не возвращает).
        """
        dept_param = request.args.get("department")
        result = tools.list_roles(db_path=_db())

        # Поднимаем поля capabilities.{llm,model,temperature,max_tokens,system_prompt}
        # на верхний уровень — фронт ждёт плоский формат (r.model и т.п.).
        for role in result.get("роли", []):
            caps = role.get("capabilities") or {}
            if isinstance(caps, dict):
                for key in ("llm", "model", "temperature", "max_tokens", "system_prompt"):
                    if key in caps and key not in role:
                        role[key] = caps[key]

        # S9.2: подтягиваем department_id напрямую из БД (tools.list_roles не возвращает).
        conn = db._connect(_db())  # type: ignore
        try:
            rows = conn.execute("SELECT name, department_id FROM roles").fetchall()
        finally:
            conn.close()
        dept_by_name: dict[str, Optional[str]] = {}
        for r in rows:
            try:
                dept_by_name[r["name"]] = r["department_id"]
            except Exception:
                # Колонка department_id может отсутствовать в старых БД (до S8.1) — игнорируем.
                pass
        for role in result.get("роли", []):
            role["department_id"] = dept_by_name.get(role.get("name"))

        # Фильтрация по department, если запрошена конкретная (не __all__).
        if dept_param and dept_param != "__all__":
            filtered = [
                r for r in result.get("роли", [])
                if (r.get("department_id") is None) or (r.get("department_id") == dept_param)
            ]
            result["роли"] = filtered
            result["всего"] = len(filtered)

        return jsonify(result)

    @app.post("/api/roles")
    def api_create_role() -> Any:
        data = request.get_json(silent=True) or {}
        name = (data.get("name") or "").strip()
        description = (data.get("description") or "").strip()
        if not name:
            return jsonify({"статус": "error", "status": "error", "причина": "name обязателен", "reason": "name обязателен"}), 400
        import re as _re2
        if not _re2.match(r'^[a-z][a-z0-9-]{0,31}$', name):
            return jsonify({"статус": "error", "status": "error", "причина": "name должен быть slug ^[a-z][a-z0-9-]{1,32}$", "reason": "name должен быть slug ^[a-z][a-z0-9-]{1,32}$"}), 400
        caps = {
            "llm": data.get("llm", "claude"),
            "model": data.get("model", ""),
            "temperature": data.get("temperature", 1.0),
            "max_tokens": data.get("max_tokens", 8096),
            "system_prompt": data.get("system_prompt", ""),
        }
        conn = db._connect(_db())
        try:
            existing = conn.execute("SELECT name FROM roles WHERE name = ?", (name,)).fetchone()
        finally:
            conn.close()
        if existing:
            return jsonify({"статус": "error", "status": "error", "причина": f"роль «{name}» уже существует", "reason": f"роль «{name}» уже существует"}), 409
        with db.write_lock(_db()):
            conn = db._connect(_db())
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "INSERT INTO roles (name, description, capabilities) VALUES (?, ?, ?)",
                    (name, description, json.dumps(caps, ensure_ascii=False)),
                )
                conn.execute("COMMIT")
            finally:
                conn.close()
        return jsonify({"статус": "ok", "роль": {"name": name, "description": description, **caps}}), 201

    @app.put("/api/roles/<role_name>")
    def api_update_role(role_name: str) -> Any:
        data = request.get_json(silent=True) or {}
        conn = db._connect(_db())
        try:
            row = conn.execute("SELECT * FROM roles WHERE name = ?", (role_name,)).fetchone()
        finally:
            conn.close()
        if not row:
            return jsonify({"статус": "not_found"}), 404
        old_caps = json.loads(row["capabilities"] or "{}")
        if isinstance(old_caps, list):
            old_caps = {}
        caps = {
            "llm": data.get("llm", old_caps.get("llm", "claude")),
            "model": data.get("model", old_caps.get("model", "")),
            "temperature": data.get("temperature", old_caps.get("temperature", 1.0)),
            "max_tokens": data.get("max_tokens", old_caps.get("max_tokens", 8096)),
            "system_prompt": data.get("system_prompt", old_caps.get("system_prompt", "")),
        }
        description = data.get("description", row["description"])
        with db.write_lock(_db()):
            conn = db._connect(_db())
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "UPDATE roles SET description = ?, capabilities = ? WHERE name = ?",
                    (description, json.dumps(caps, ensure_ascii=False), role_name),
                )
                conn.execute("COMMIT")
            finally:
                conn.close()
        return jsonify({"статус": "ok", "роль": {"name": role_name, "description": description, **caps}})

    @app.delete("/api/roles/<role_name>")
    def api_delete_role(role_name: str) -> Any:
        conn = db._connect(_db())
        try:
            row = conn.execute("SELECT name FROM roles WHERE name = ?", (role_name,)).fetchone()
        finally:
            conn.close()
        if not row:
            return jsonify({"статус": "not_found"}), 404
        with db.write_lock(_db()):
            conn = db._connect(_db())
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("DELETE FROM roles WHERE name = ?", (role_name,))
                conn.execute("COMMIT")
            finally:
                conn.close()
        return jsonify({"статус": "ok"})

    @app.post("/api/roles/import")
    def import_role() -> Any:
        """Import a role from a URL (GitHub raw / gist)."""
        import datetime
        import re as _re_import
        import tempfile

        import httpx as _httpx

        from roles.validator import validate_role_file

        data = request.get_json(silent=True) or {}
        url = (data.get("url") or "").strip()
        force = bool(data.get("force", False))

        if not url:
            return jsonify({"status": "error", "detail": "url is required"}), 400

        # --- 1. URL allowlist ---
        _default_allowlist = ["raw.githubusercontent.com", "gist.github.com"]
        _env_allowlist = os.environ.get("ROLES_IMPORT_ALLOWLIST", "")
        allowed_hosts: list[str] = (
            [h.strip() for h in _env_allowlist.split(",") if h.strip()]
            if _env_allowlist
            else _default_allowlist
        )
        try:
            from urllib.parse import urlparse as _urlparse
            parsed = _urlparse(url)
            host = parsed.netloc.lower()
        except Exception:
            return jsonify({"status": "error", "detail": "invalid URL"}), 400

        if not any(host == h or host.endswith("." + h) for h in allowed_hosts):
            return jsonify({
                "status": "error",
                "detail": f"URL host '{host}' is not in the allowlist ({', '.join(allowed_hosts)})",
            }), 400

        # --- 2. Download with size check ---
        _MAX_SIZE = 50 * 1024  # 50 KB

        try:
            with _httpx.stream("GET", url, timeout=10, follow_redirects=True) as resp:
                resp.raise_for_status()

                # Size check via Content-Length header first
                content_length = resp.headers.get("content-length")
                if content_length is not None:
                    try:
                        if int(content_length) > _MAX_SIZE:
                            return jsonify({
                                "status": "error",
                                "detail": f"Content-Length {content_length} exceeds 50KB limit",
                            }), 400
                    except ValueError:
                        pass

                # --- 3. Content-Type check ---
                _ALLOWED_CONTENT_TYPES = ("text/markdown", "text/plain", "application/octet-stream")
                ct = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
                if ct and ct not in _ALLOWED_CONTENT_TYPES:
                    return jsonify({
                        "status": "error",
                        "detail": (
                            f"content-type '{ct}' not allowed "
                            f"(expected text/markdown, text/plain or application/octet-stream)"
                        ),
                    }), 400

                # Read body with hard size limit
                chunks: list[bytes] = []
                total = 0
                for chunk in resp.iter_bytes(chunk_size=4096):
                    total += len(chunk)
                    if total > _MAX_SIZE:
                        return jsonify({
                            "status": "error",
                            "detail": "response body exceeds 50KB limit",
                        }), 400
                    chunks.append(chunk)

        except _httpx.TimeoutException:
            return jsonify({"status": "error", "detail": "request timed out"}), 400
        except _httpx.HTTPStatusError as exc:
            return jsonify({"status": "error", "detail": f"download failed: HTTP {exc.response.status_code}"}), 400
        except _httpx.RequestError as exc:
            return jsonify({"status": "error", "detail": f"download failed: {exc}"}), 400
        content_bytes = b"".join(chunks)

        # --- 4. Validate via validate_role_file (write to tmp file) ---
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(content_bytes)

        try:
            val_result = validate_role_file(tmp_path)
        finally:
            try:
                tmp_path.unlink()
            except OSError:
                pass

        if not val_result.ok:
            return jsonify({
                "status": "error",
                "detail": "role validation failed",
                "errors": val_result.errors,
            }), 422

        # --- 5. Extract name from validated frontmatter ---
        role_name = val_result.config.name  # type: ignore[union-attr]
        _SLUG_RE = _re_import.compile(r"^[a-z][a-z0-9-]{1,31}$")
        if not _SLUG_RE.match(role_name):
            return jsonify({
                "status": "error",
                "detail": f"role name '{role_name}' does not match required slug pattern",
            }), 400

        # --- 6. Path traversal guard: always write to _ROLES_DIR/<name>.md ---
        dest_path = (_ROLES_DIR / f"{role_name}.md").resolve()
        if dest_path.parent.resolve() != _ROLES_DIR.resolve():
            return jsonify({
                "status": "error",
                "detail": "path traversal detected in role name",
            }), 400

        # --- 7. Conflict check ---
        if dest_path.exists() and not force:
            return jsonify({
                "status": "error",
                "detail": f"roles/{role_name}.md already exists; use force=true to overwrite",
            }), 409

        # --- 8. Write file ---
        _ROLES_DIR.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(content_bytes)
        size_bytes = len(content_bytes)
        log.info("import_role: saved %s (%d bytes) from %s", dest_path.name, size_bytes, url)

        # --- 9. Append to import log ---
        import_log_path = _ROLES_DIR / ".import-log.json"
        log_entry = {
            "name": role_name,
            "url": url,
            "imported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "size_bytes": size_bytes,
        }
        try:
            existing_log: list = []
            if import_log_path.exists():
                try:
                    existing_log = json.loads(import_log_path.read_text(encoding="utf-8"))
                    if not isinstance(existing_log, list):
                        existing_log = []
                except (json.JSONDecodeError, OSError):
                    existing_log = []
            existing_log.append(log_entry)
            import_log_path.write_text(
                json.dumps(existing_log, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            log.warning("import_role: could not write .import-log.json: %s", exc)

        return jsonify({
            "status": "ok",
            "name": role_name,
            "path": f"roles/{role_name}.md",
            "size": size_bytes,
        })

    # === Team session ===

    @app.post("/api/team/start")
    def api_team_start() -> Any:
        body = request.get_json(silent=True) or {}
        output_locale = body.get("output_locale", "ru")
        # Принимаем только ru | en; всё остальное → ru
        if output_locale not in ("ru", "en"):
            output_locale = "ru"
        # Сохраняем locale рядом с БД (data/ в prod, tmp_path в тестах)
        locale_file = _db().parent / ".output_locale"
        locale_file.parent.mkdir(exist_ok=True)
        locale_file.write_text(output_locale)

        # S3.4: user_expertise — сохраняем рядом с БД, devboard-work.sh читает
        user_expertise = body.get("user_expertise", "non-tech")
        if user_expertise not in ("non-tech", "tech"):
            user_expertise = "non-tech"
        expertise_file = _db().parent / ".user_expertise"
        expertise_file.parent.mkdir(exist_ok=True)
        expertise_file.write_text(user_expertise)

        # Роль для запуска. Phase 1.7 fix:
        # Если role явно не передан или = managing-director (legacy default из JS),
        # делаем smart-default: смотрим какая очередь не пустая и запускаем
        # соответствующего lead-а. Иначе запускаем явно указанную роль.
        explicit_role = body.get("role")
        if explicit_role and explicit_role != "managing-director":
            role = explicit_role
        else:
            # Smart-default: ищем lead-роль с самой свежей todo задачей.
            role = _smart_default_role(_db())

        res = _start_team_process(role=role)
        if not res["ok"]:
            return jsonify({"статус": "error", **res}), 409
        return jsonify({"статус": "ok", **res})

    @app.post("/api/team/stop")
    def api_team_stop() -> Any:
        res = _stop_team_process()
        if not res["ok"]:
            return jsonify({"статус": "error", **res}), 409
        return jsonify({"статус": "ok"})

    @app.get("/api/team/status")
    def api_team_status() -> Any:
        s = _team_status()
        s["auto_mode"] = _team_state["auto_mode"]
        s["auto_pause_reason"] = _team_state.get("auto_pause_reason")
        s["starts_last_hour"] = len(_team_state["starts_history"])
        return jsonify(s)

    @app.post("/api/team/auto")
    def api_team_auto() -> Any:
        data = request.get_json(silent=True) or {}
        enabled = bool(data.get("enabled"))
        _team_state["auto_mode"] = enabled
        # При выключении сбрасываем причину паузы
        if not enabled:
            _team_state["auto_pause_reason"] = None
        return jsonify({
            "статус": "ok",
            "auto_mode": enabled,
            "starts_last_hour": len(_team_state["starts_history"]),
        })

    @app.get("/api/team/stream")
    def api_team_stream() -> Response:
        def event_stream():
            yield "retry: 3000\n\n"
            while True:
                try:
                    item = _team_state["queue"].get(timeout=15)
                    # item — dict {ts, human, raw} (или старая строка для совместимости)
                    if isinstance(item, str):
                        item = {"ts": "", "human": item, "raw": item}
                    yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                except Empty:
                    yield ": heartbeat\n\n"

        return Response(event_stream(), mimetype="text/event-stream")

    @app.get("/api/usage")
    def api_usage() -> Any:
        return jsonify(db.usage_summary(_db()))

    # === Stats aggregates ===

    # Кэш для /api/stats/aggregates: dict keyed by range → (timestamp, payload)
    _stats_cache: dict[str, tuple[float, Any]] = {}
    _STATS_TTL = 60.0  # секунд

    @app.get("/api/stats/aggregates")
    def api_stats_aggregates() -> Any:
        """Агрегированная статистика по диапазону.

        ?range=today|24h|week|all  (default: 24h)
        Результат кэшируется 60 с.
        """
        rng = request.args.get("range", "24h")
        if rng not in ("today", "24h", "week", "all"):
            rng = "24h"

        now_ts = time.time()
        cached = _stats_cache.get(rng)
        if cached and (now_ts - cached[0]) < _STATS_TTL:
            return jsonify(cached[1])

        # WHERE-фрагмент по finished_at (unix timestamp).
        # where_clause  — полный WHERE для одиночных запросов (или пустая строка)
        # where_and     — AND-условие для добавления к существующему WHERE
        if rng == "today":
            where_clause = "WHERE date(finished_at, 'unixepoch', 'localtime') = date('now', 'localtime')"
            where_and = "AND date(finished_at, 'unixepoch', 'localtime') = date('now', 'localtime')"
        elif rng == "24h":
            where_clause = "WHERE finished_at >= strftime('%s', 'now', '-24 hours')"
            where_and = "AND finished_at >= strftime('%s', 'now', '-24 hours')"
        elif rng == "week":
            where_clause = "WHERE finished_at >= strftime('%s', 'now', '-7 days')"
            where_and = "AND finished_at >= strftime('%s', 'now', '-7 days')"
        else:
            where_clause = ""
            where_and = ""

        conn = db._connect(_db())  # type: ignore
        try:
            # Основные счётчики сессий
            row = conn.execute(
                f"""
                SELECT
                    COUNT(*) AS sessions,
                    COALESCE(SUM(num_turns), 0) AS turns,
                    COALESCE(SUM(total_cost_usd), 0.0) AS cost_usd,
                    COALESCE(SUM(duration_ms) / 1000.0 / 3600.0, 0.0) AS hours_worked
                FROM claude_sessions {where_clause}
                """
            ).fetchone()
            sessions = row["sessions"] or 0
            turns = row["turns"] or 0
            cost_usd = round(float(row["cost_usd"] or 0), 4)
            hours_worked = round(float(row["hours_worked"] or 0), 2)

            # Разбивка по моделям
            model_rows = conn.execute(
                f"""
                SELECT
                    model,
                    COUNT(*) AS sessions,
                    COALESCE(SUM(input_tokens), 0) AS input_tokens,
                    COALESCE(SUM(output_tokens), 0) AS output_tokens,
                    COALESCE(SUM(total_cost_usd), 0.0) AS cost_usd
                FROM claude_sessions
                WHERE model IS NOT NULL {where_and}
                GROUP BY model
                ORDER BY cost_usd DESC
                """
            ).fetchall()
            models = [
                {
                    "model": r["model"],
                    "sessions": r["sessions"],
                    "input_tokens": r["input_tokens"],
                    "output_tokens": r["output_tokens"],
                    "cost_usd": round(float(r["cost_usd"]), 4),
                }
                for r in model_rows
            ]

            # Самая длинная сессия (по num_turns)
            longest_row = conn.execute(
                f"""
                SELECT id AS session_id, COALESCE(num_turns, 0) AS turns
                FROM claude_sessions {where_clause}
                ORDER BY num_turns DESC
                LIMIT 1
                """
            ).fetchone()
            longest_turn = (
                {"session_id": str(longest_row["session_id"]), "turns": longest_row["turns"]}
                if longest_row
                else None
            )

            # Самый дорогой день
            expensive_row = conn.execute(
                f"""
                SELECT
                    date(finished_at, 'unixepoch', 'localtime') AS day,
                    COALESCE(SUM(total_cost_usd), 0.0) AS cost
                FROM claude_sessions {where_clause}
                GROUP BY day
                ORDER BY cost DESC
                LIMIT 1
                """
            ).fetchone()
            most_expensive_day = (
                {"date": expensive_row["day"], "cost": round(float(expensive_row["cost"]), 4)}
                if expensive_row and expensive_row["day"]
                else None
            )

            # Счётчики задач по ролям
            role_rows = conn.execute(
                """
                SELECT
                    COALESCE(assignee, 'unknown') AS name,
                    SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS done,
                    SUM(CASE WHEN status = 'wip' THEN 1 ELSE 0 END) AS wip,
                    SUM(CASE WHEN status = 'todo' THEN 1 ELSE 0 END) AS todo
                FROM tasks
                WHERE assignee NOT IN ('пользователь', 'user')
                GROUP BY assignee
                ORDER BY done DESC
                """
            ).fetchall()
            roles = [
                {"name": r["name"], "done": r["done"], "wip": r["wip"], "todo": r["todo"]}
                for r in role_rows
            ]

            # most_productive_role
            most_productive_role = roles[0]["name"] if roles else None

            # Fastest task: min time between created_at → completed_at (only done tasks)
            fastest_row = conn.execute(
                """
                SELECT id,
                    ROUND((completed_at - created_at) / 60.0, 1) AS minutes
                FROM tasks
                WHERE status = 'done'
                    AND completed_at IS NOT NULL
                    AND created_at IS NOT NULL
                    AND completed_at > created_at
                ORDER BY minutes ASC
                LIMIT 1
                """
            ).fetchone()
            fastest_task = (
                {"id": fastest_row["id"], "minutes": float(fastest_row["minutes"])}
                if fastest_row
                else None
            )

            # Hourly activity: 0-23 — число сессий финишировавших в этот час
            hour_rows = conn.execute(
                f"""
                SELECT
                    CAST(strftime('%H', finished_at, 'unixepoch', 'localtime') AS INTEGER) AS hour,
                    COUNT(*) AS count
                FROM claude_sessions {where_clause}
                GROUP BY hour
                """
            ).fetchall()
            hour_map = {r["hour"]: r["count"] for r in hour_rows}
            hourly_activity = [{"hour": h, "count": hour_map.get(h, 0)} for h in range(24)]

            # === Lifetime task counters (NOT filtered by range) ===
            # Всего сделано задач (статус = 'done')
            tasks_total_done_row = conn.execute(
                "SELECT COUNT(*) AS count FROM tasks WHERE status = 'done'"
            ).fetchone()
            tasks_total_done = tasks_total_done_row["count"] or 0

            # Всего создано задач
            tasks_total_created_row = conn.execute(
                "SELECT COUNT(*) AS count FROM tasks"
            ).fetchone()
            tasks_total_created = tasks_total_created_row["count"] or 0

            # Сейчас в работе (wip + review + needs_approval)
            tasks_in_progress_row = conn.execute(
                "SELECT COUNT(*) AS count FROM tasks WHERE status IN ('wip', 'review', 'needs_approval')"
            ).fetchone()
            tasks_in_progress = tasks_in_progress_row["count"] or 0

            # Completion rate (завершённые от всех созданных)
            tasks_completion_rate = (
                round(tasks_total_done / tasks_total_created, 2)
                if tasks_total_created > 0
                else 0.0
            )

        finally:
            conn.close()

        # Лёгкий парсинг team.log для files_changed / lines_written / chat_chars
        files_changed = 0
        lines_written = 0
        chat_chars = 0
        try:
            if _LIVE_LOG.exists():
                import re as _re_log
                _tool_write_re = _re_log.compile(r'"name"\s*:\s*"(Write|Edit)"')
                _lines_re = _re_log.compile(r'"new_string"\s*:\s*"((?:[^"\\]|\\.)*)"')
                _chat_re = _re_log.compile(r'"text"\s*:\s*"((?:[^"\\]|\\.)*)"')
                content = _LIVE_LOG.read_text(encoding="utf-8", errors="ignore")
                files_changed = len(_tool_write_re.findall(content))
                for m in _lines_re.finditer(content):
                    lines_written += m.group(1).count("\\n") + 1
                for m in _chat_re.finditer(content):
                    chat_chars += len(m.group(1))
        except Exception as exc:  # noqa: BLE001
            log.debug("stats: не смог распарсить team.log: %s", exc)

        payload: dict[str, Any] = {
            "range": rng,
            "sessions": sessions,
            "turns": turns,
            "cost_usd": cost_usd,
            "files_changed": files_changed,
            "lines_written": lines_written,
            "chat_chars": chat_chars,
            "hours_worked": hours_worked,
            "models": models,
            "roles": roles,
            "hourly_activity": hourly_activity,
            "top": {
                "longest_turn": longest_turn,
                "most_expensive_day": most_expensive_day,
                "fastest_task": fastest_task,
                "most_productive_role": most_productive_role,
            },
            # Lifetime task counters (always, not range-filtered)
            "tasks_total_done": tasks_total_done,
            "tasks_total_created": tasks_total_created,
            "tasks_in_progress": tasks_in_progress,
            "tasks_completion_rate": tasks_completion_rate,
        }
        _stats_cache[rng] = (now_ts, payload)
        return jsonify(payload)

    @app.get("/api/team/silence")
    def api_team_silence() -> Any:
        """Проверка молчания тимлида: была ли последняя сессия, ответил ли тимлид в чате.

        Возвращает {silent: bool, last_session_at, last_chat_at, since_session_min, reason}.
        """
        conn = db._connect(_db())  # type: ignore
        try:
            row = conn.execute(
                "SELECT MAX(finished_at) FROM claude_sessions"
            ).fetchone()
            last_session = row[0]
            row = conn.execute(
                "SELECT MAX(created_at) FROM chat_messages WHERE author='тимлид'"
            ).fetchone()
            last_chat = row[0]
        finally:
            conn.close()
        import time as _t
        now = _t.time()
        if not last_session:
            return jsonify({"silent": False, "reason": "сессий ещё не было"})
        since = (now - last_session) / 60
        # Тимлид молчит, если последняя сессия была >2 мин назад
        # и при этом тимлид НЕ оставлял chat-сообщения после её завершения.
        if since < 2:
            return jsonify({"silent": False, "reason": "сессия только что закончилась, дождись chat_post"})
        if last_chat and last_chat >= last_session:
            return jsonify({"silent": False, "reason": "тимлид отчитался в чате"})
        return jsonify({
            "silent": True,
            "last_session_at": last_session,
            "last_chat_at": last_chat,
            "since_session_min": int(since),
            "reason": f"сессия завершилась {int(since)} мин назад, итогов в чате нет",
        })

    @app.get("/api/router/pick")
    def api_router_pick() -> Any:
        """Прогноз модели для следующей сессии тимлида.

        Используется UI чтобы показать «🤖 роутер: sonnet» в шапке до того
        как пользователь нажмёт «▶ Запустить команду».
        """
        from devboard_tasks import router
        return jsonify(router.pick_from_db(_db()))

    @app.get("/api/chat")
    def api_chat_list() -> Any:
        since = int(request.args.get("since", 0))
        limit = int(request.args.get("limit", 100))
        # S8.3: ?department=<id> → фильтр по department_id
        # ?department=__global__ → глобальный канал (department_id IS NULL)
        # не указан → default 'dev'
        dept_param = request.args.get("department")
        if dept_param == "__global__":
            chat_dept = None
        elif dept_param is not None:
            chat_dept = dept_param
        else:
            chat_dept = "dev"
        msgs = db.list_chat_messages(_db(), since=since, limit=limit, department_id=chat_dept)
        return jsonify({"messages": msgs})

    @app.post("/api/chat")
    def api_chat_post() -> Any:
        data = request.get_json(silent=True) or {}
        author = data.get("author", "пользователь")
        text = data.get("text", "")
        # S8.3: ?department=<id> → department_id для нового сообщения
        # ?department=__global__ → глобальный канал (department_id=None)
        # не указан → default 'dev'
        dept_param = request.args.get("department")
        if dept_param == "__global__":
            chat_dept: Any = None
        elif dept_param is not None:
            chat_dept = dept_param
        else:
            chat_dept = "dev"
        try:
            msg = db.post_chat_message(_db(), author, text, department_id=chat_dept)
        except ValueError as exc:
            return jsonify({"статус": "error", "status": "error", "причина": str(exc), "reason": str(exc)}), 400
        return jsonify({"статус": "ok", "сообщение": msg}), 201

    # === Planning sessions (ADR-009 §2.4 / §2.7.3) ===
    # Read-only HTTP-проекция planning_sessions для UI-индикатора в общем чате.
    # MCP-tools (start/collect/finalize) живут в mcp_server — UI их не дёргает.

    @app.get("/api/planning/active")
    def api_planning_active() -> Any:
        """Список активных планёрок (phase != 'done').

        Используется баннером в шапке общего чата: пока есть хотя бы одна
        активная планёрка — баннер виден. Polling из app.js раз в REFRESH_MS.
        Возвращает короткий summary без discussion_log (детали — через /api/planning/<id>).
        """
        conn = db._connect(_db())
        try:
            rows = conn.execute(
                """
                SELECT id, owner_request, phase, departments_involved,
                       discussion_log, started_at, finished_at
                FROM planning_sessions
                WHERE phase != 'done' AND finished_at IS NULL
                ORDER BY started_at ASC
                """
            ).fetchall()
        finally:
            conn.close()

        import json as _json
        sessions: list[dict[str, Any]] = []
        for r in rows:
            try:
                depts = _json.loads(r["departments_involved"]) if r["departments_involved"] else []
            except (ValueError, TypeError):
                depts = []
            try:
                replies = _json.loads(r["discussion_log"]) if r["discussion_log"] else []
            except (ValueError, TypeError):
                replies = []
            sessions.append({
                "id": r["id"],
                "owner_request": r["owner_request"],
                "phase": r["phase"],
                "departments_involved": depts,
                "replies_count": len(replies) if isinstance(replies, list) else 0,
                "started_at": r["started_at"],
                "finished_at": r["finished_at"],
            })
        return jsonify({"sessions": sessions})

    @app.get("/api/planning/<session_id>")
    def api_planning_get(session_id: str) -> Any:
        """Детали одной планёрки — для раскрывающейся панели.

        Используется panel'ом discussion_log в общем чате (polling).
        404 если planning_session не существует.
        """
        sess = db.planning_session_get(_db(), session_id)
        if sess is None:
            return jsonify({
                "статус": "not_found", "status": "not_found",
                "причина": f"planning_session {session_id!r} не найдена",
                "reason": f"planning_session {session_id!r} not found",
            }), 404
        # Только публично-интересные поля (не отдаём пока ничего лишнего).
        return jsonify({
            "id":                   sess["id"],
            "owner_request":        sess["owner_request"],
            "departments_involved": sess["departments_involved"],
            "discussion_log":       sess["discussion_log"],
            "phase":                sess["phase"],
            "started_at":           sess["started_at"],
            "finished_at":          sess["finished_at"],
            "owner_answer":         sess["owner_answer"],
        })

    @app.get("/api/inbox")
    def api_inbox() -> Any:
        """Что требует личного внимания пользователя.

        Простое правило: «если задача в столбце нужно-одобрить / на-приёмке /
        назначена-мне — она в моём Inbox».

          - approvals: ВСЕ задачи status=needs_approval. Если карточка
                       физически попала в эту колонку — значит требует
                       одобрения, неважно кто assignee и какие метки.
                       Метка `destructive` используется как ВИЗУАЛЬНЫЙ маркер
                       (карточка подсвечивается красным во frontend), но не
                       влияет на группировку.
          - reviews:   ВСЕ status=review.
          - questions: assignee=пользователь, status=todo (или needs_approval без
                       поглощения в approvals — здесь approvals имеет приоритет,
                       поэтому needs_approval-задача не попадёт сюда).
        Каждая задача попадает РОВНО в одну группу: approvals > reviews > questions.

        S9.2: поддержка ?department=<id>:
          - ?department=__all__   → без фильтра (показать всё)
          - ?department=<id>      → только задачи этого отдела
          - не указан             → default 'dev' (backward compat)
        """
        dept_param = request.args.get("department")
        if dept_param == "__all__":
            dept_filter: Optional[str] = None
        elif dept_param is not None:
            dept_filter = dept_param
        else:
            dept_filter = "dev"

        def _by_dept(tasks: list) -> list:
            if dept_filter is None:
                return tasks
            return [t for t in tasks if t.get("department_id") == dept_filter]

        approval_tasks = _by_dept(db.list_tasks(_db(), status="needs_approval", limit=200))
        review_tasks = _by_dept(db.list_tasks(_db(), status="review", limit=200))
        approval_ids = {t["id"] for t in approval_tasks}
        review_ids = {t["id"] for t in review_tasks}
        # questions: задачи назначенные пользователю, не попавшие в первые две группы.
        questions: list = []
        for t in _by_dept(db.list_tasks(_db(), assignee="пользователь", limit=200)):
            if t["status"] in ("done", "blocked"):
                continue
            if t["id"] in approval_ids or t["id"] in review_ids:
                continue
            if t["status"] in ("todo", "needs_approval"):
                questions.append(t)
        total = len(approval_tasks) + len(review_tasks) + len(questions)
        return jsonify({
            "approvals": approval_tasks,
            "reviews": review_tasks,
            "questions": questions,
            "total": total,
        })

    @app.get("/api/manager/bootstrap")
    def api_manager_bootstrap() -> Any:
        """Bootstrap-контекст для роли `managing-director`.

        Source-of-truth: ADR-007 §2.4 (Bootstrap mode — экономия токенов),
        ADR-009 §2.2 (что Управляющему нужно при старте сессии).

        Используется `commands/devboard-work.sh` в начале сессии — единым
        вызовом подгружает всё что нужно Управляющему, чтобы дальше за
        каждый turn передавать только дельту (см. ADR-006).

        Возвращает JSON c 6 полями:
          - inboxes:                 list[dict] — агрегат `inbox_summary` по
                                     всем активным отделам (wip/review/blocked
                                     counts + last_chat_msg_time).
          - chat_recent:             list[dict] — последние 50 сообщений
                                     общего чата (department_id IS NULL).
          - adr_list:                list[dict] — все ADR из docs/adr/*.md
                                     c полями {number, title, status, file}.
          - memory_notes:            list[dict] — `manager_chunk_recent(source='note', limit=20)`.
          - memory_recall:           list[dict] — `manager_chunk_recent(source='recall', limit=10)`.
          - planning_sessions_active list[dict] — все planning_sessions
                                     с phase != 'done'.

        Endpoint открытый (как другие dashboard endpoints) — предназначен
        для роли managing-director (role gate уровня MCP-tool остаётся
        первичным механизмом доступа к памяти). Bootstrap вызывается
        ровно один раз в начале сессии скриптом запуска, не в каждый turn.

        Performance: цель <500ms. Все запросы — один db.* вызов каждый,
        FK pragma и схема прогреты через init_db() при старте.
        """
        db_path = _db()

        # 1. Inboxes — агрегат по отделам (один SQL-запрос с LEFT JOIN + GROUP BY).
        try:
            inboxes = db.inbox_summary(db_path)
        except Exception as exc:  # noqa: BLE001
            log.warning("bootstrap: inbox_summary failed: %s", exc)
            inboxes = []

        # 2. chat_recent — последние 50 сообщений глобального канала.
        # list_chat_messages сортирует по id ASC; для «последние N» получаем
        # ВСЕ с since=0, потом берём хвост — но это неэффективно если их много.
        # Используем прямой SQL через _db_path (без копирования всей функции).
        try:
            import sqlite3 as _sqlite3
            conn = _sqlite3.connect(str(db_path))
            conn.row_factory = _sqlite3.Row
            try:
                rows = conn.execute(
                    "SELECT * FROM chat_messages WHERE department_id IS NULL "
                    "ORDER BY id DESC LIMIT 50"
                ).fetchall()
                # Возвращаем в хронологическом порядке (старые → новые).
                chat_recent = [
                    {
                        "id":            r["id"],
                        "author":        r["author"],
                        "text":          r["text"],
                        "created_at":    r["created_at"],
                        "department_id": r["department_id"],
                    }
                    for r in reversed(rows)
                ]
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001
            log.warning("bootstrap: chat_recent failed: %s", exc)
            chat_recent = []

        # 3. adr_list — парсинг docs/adr/*.md.
        try:
            adr_list = _list_adr_files()
        except Exception as exc:  # noqa: BLE001
            log.warning("bootstrap: adr_list failed: %s", exc)
            adr_list = []

        # 4. memory_notes — последние 20 чанков source='note'.
        try:
            memory_notes = db.manager_chunk_recent(db_path, source="note", limit=20)
        except Exception as exc:  # noqa: BLE001
            log.warning("bootstrap: memory_notes failed: %s", exc)
            memory_notes = []

        # 5. memory_recall — последние 10 чанков source='recall'.
        try:
            memory_recall = db.manager_chunk_recent(db_path, source="recall", limit=10)
        except Exception as exc:  # noqa: BLE001
            log.warning("bootstrap: memory_recall failed: %s", exc)
            memory_recall = []

        # 6. planning_sessions_active — все с phase != 'done'.
        try:
            import sqlite3 as _sqlite3b
            conn = _sqlite3b.connect(str(db_path))
            conn.row_factory = _sqlite3b.Row
            try:
                rows = conn.execute(
                    "SELECT id FROM planning_sessions WHERE phase != 'done' "
                    "ORDER BY started_at DESC"
                ).fetchall()
                planning_sessions_active = [
                    db.planning_session_get(db_path, r["id"]) for r in rows
                ]
                planning_sessions_active = [s for s in planning_sessions_active if s is not None]
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001
            log.warning("bootstrap: planning_sessions_active failed: %s", exc)
            planning_sessions_active = []

        return jsonify({
            "inboxes":                  inboxes,
            "chat_recent":              chat_recent,
            "adr_list":                 adr_list,
            "memory_notes":             memory_notes,
            "memory_recall":            memory_recall,
            "planning_sessions_active": planning_sessions_active,
        })

    @app.get("/api/settings/static-info")
    def api_settings_static_info() -> Any:
        """Статическая информация для страницы Settings: лимиты авто-режима, бекапы."""
        backups_dir = _DATA_DIR / "backups"
        last_backup = None
        try:
            if backups_dir.exists():
                files = sorted(
                    [f for f in backups_dir.iterdir() if f.is_file() and f.suffix == ".db"],
                    key=lambda f: f.stat().st_mtime,
                    reverse=True,
                )
                if files:
                    f = files[0]
                    size_kb = round(f.stat().st_size / 1024)
                    last_backup = {"name": f.name, "size_kb": size_kb}
        except Exception:
            pass
        return jsonify({
            "auto_limits": {"max_per_hour": 20, "min_interval_sec": 30},
            "backups_path": "data/backups",
            "last_backup": last_backup,
        })

    # === Onboarding: company context (B2 1.6) ===

    _COMPANY_CONTEXT_PATH = _DATA_DIR / "company-context.md"

    @app.get("/api/onboarding/company-context")
    def api_get_company_context() -> Any:
        """Вернуть содержимое data/company-context.md.

        Returns:
            {"exists": True, "content": "<markdown>"} — если файл есть.
            {"exists": False, "content": null} — если файла нет.
        """
        if _COMPANY_CONTEXT_PATH.is_file():
            content = _COMPANY_CONTEXT_PATH.read_text(encoding="utf-8")
            return jsonify({"exists": True, "content": content})
        return jsonify({"exists": False, "content": None})

    @app.post("/api/onboarding/company-context")
    def api_post_company_context() -> Any:
        """Сохранить контекст компании в data/company-context.md.

        Body (JSON): {
            "name": "...",
            "description": "...",
            "brand_voice": "...",   # опционально
            "values": "...",        # опционально
            "audience": "..."       # опционально
        }

        Returns:
            {"status": "ok", "path": "data/company-context.md"}
        """
        data = request.get_json(silent=True) or {}
        name = (data.get("name") or "").strip()
        description = (data.get("description") or "").strip()
        brand_voice = (data.get("brand_voice") or "").strip()
        values = (data.get("values") or "").strip()
        audience = (data.get("audience") or "").strip()

        if not name:
            return jsonify({
                "status": "error",
                "статус": "error",
                "reason": "поле 'name' обязательно",
                "причина": "поле 'name' обязательно",
            }), 400

        md_lines = [
            "---",
            f"name: {name}",
            f"description: {description}",
            f"brand_voice: {brand_voice}",
            f"values: {values}",
            f"audience: {audience}",
            "---",
            "",
            "## Контекст компании",
            "",
            f"**Название:** {name}",
            "",
            f"**Чем занимается:** {description}",
            "",
            f"**Brand voice:** {brand_voice}",
            "",
            f"**Ценности:** {values}",
            "",
            f"**Целевая аудитория:** {audience}",
            "",
        ]
        md_content = "\n".join(md_lines)

        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        _COMPANY_CONTEXT_PATH.write_text(md_content, encoding="utf-8")

        return jsonify({"status": "ok", "path": "data/company-context.md"}), 200

    @app.post("/api/open-folder")
    def api_open_folder() -> Any:
        """Открыть папку в системном файловом менеджере (macOS: Finder, Linux: xdg-open).

        Принимает {"path": "data/backups"} — относительный путь от repo root.
        Используется кнопкой «Открыть папку» на странице Settings.
        """
        data = request.get_json(silent=True) or {}
        rel_path = (data.get("path") or "").strip()
        if not rel_path:
            return jsonify({"статус": "error", "status": "error", "причина": "path обязателен", "reason": "path обязателен"}), 400
        # Безопасность: разрешаем только data/ — не допускаем path traversal
        target = (_REPO_ROOT / rel_path).resolve()
        data_resolved = (_DATA_DIR).resolve()
        try:
            target.relative_to(data_resolved)
        except ValueError:
            return jsonify({"статус": "error", "status": "error", "причина": "доступ только к папке data/", "reason": "доступ только к папке data/"}), 403
        if not target.exists():
            target.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            elif sys.platform == "win32":
                subprocess.Popen(["explorer", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except Exception as exc:  # noqa: BLE001
            return jsonify({"статус": "error", "status": "error", "причина": str(exc), "reason": str(exc)}), 500
        return jsonify({"статус": "ok", "path": str(target)})

    @app.get("/healthz")
    def healthz() -> Any:
        return jsonify({"status": "ok", "db": str(_db())})

    # === Demo data ===

    @app.post("/api/demo")
    def create_demo_data() -> Any:
        """Создаёт демо-данные в канбане.

        Идемпотентен: если demo-данные уже есть (label "demo") — возвращает 200.
        Иначе создаёт:
          - 1 epic «Build a landing page» (status=wip, labels=["demo"])
          - 3 subtasks с разными статусами (todo/wip/review), labels=["demo"]
          - 1 needs_approval задачу «Deploy to production» (labels=["demo","destructive"])
        Возвращает: {"created": [list of task ids], "already_exists": bool}
        """
        # Проверяем идемпотентность — есть ли уже задачи с label "demo"
        existing = db.list_tasks(_db(), label="demo", limit=1)
        if existing:
            return jsonify({"created": [], "already_exists": True})

        created_ids: list[str] = []

        # Определяем assignee через текущий отдел (X-Department > cookie > fallback 'dev')
        _demo_dept = (
            request.headers.get("X-Department")
            or request.cookies.get("current_department")
            or "dev"
        )
        _demo_lead = _find_lead_for_department(_db(), _demo_dept) or "тимлид"

        # Epic: Build a landing page
        # Используем db.insert_task напрямую — assignee может быть non-legacy slug
        # (например, marketing-lead), который tools.create_task не знает.
        _epic_task = db.insert_task(
            _db(),
            title="Build a landing page",
            description="Верстаем лендинг для продукта. Эпик-задача.",
            assignee=_demo_lead,
            reporter="пользователь",
            priority="P1",
            status="wip",
            labels=["demo"],
            department_id=_demo_dept,
        )
        epic_id = _epic_task["id"]
        created_ids.append(epic_id)

        # Subtask 1: todo
        sub1_res = tools.create_task(
            title="Design hero section",
            description="Создать макет главного блока лендинга.",
            assignee="frontend",
            reporter="тимлид",
            priority="P2",
            parent_id=epic_id,
            status="todo",
            labels=["demo"],
            db_path=_db(),
        )
        created_ids.append(sub1_res["задача"]["id"])

        # Subtask 2: wip
        sub2_res = tools.create_task(
            title="Implement responsive layout",
            description="Адаптивная вёрстка под мобильные устройства.",
            assignee="frontend",
            reporter="тимлид",
            priority="P2",
            parent_id=epic_id,
            status="wip",
            labels=["demo"],
            db_path=_db(),
        )
        created_ids.append(sub2_res["задача"]["id"])

        # Subtask 3: review
        sub3_res = tools.create_task(
            title="Write copy for landing page",
            description="Тексты и заголовки для лендинга.",
            assignee="техписатель",
            reporter="тимлид",
            priority="P3",
            parent_id=epic_id,
            status="review",
            labels=["demo"],
            db_path=_db(),
        )
        created_ids.append(sub3_res["задача"]["id"])

        # needs_approval: Deploy to production
        deploy_res = tools.create_task(
            title="Deploy to production",
            description="Деплой на продакшн — требует одобрения пользователя.",
            assignee="пользователь",
            reporter="тимлид",
            priority="P0",
            requires_approval=True,
            status="needs_approval",
            labels=["demo", "destructive"],
            db_path=_db(),
        )
        created_ids.append(deploy_res["задача"]["id"])

        # Chat messages to seed the feed
        db.post_chat_message(_db(), "тимлид", "Проект запущен! Смотрите задачи в канбане.")
        db.post_chat_message(_db(), "бэкенд", "Готово, лендинг задизайнен и написан.")

        return jsonify({"created": created_ids, "already_exists": False}), 201

    @app.delete("/api/demo")
    def clear_demo_data() -> Any:
        """Удаляет все задачи с label "demo".

        Возвращает: {"deleted": N}
        """
        demo_tasks = db.list_tasks(_db(), label="demo", limit=1000)
        if not demo_tasks:
            return jsonify({"deleted": 0})

        # Сортируем: сначала задачи у которых есть parent (дети), потом корневые (epic)
        # чтобы не нарушать FK constraint parent_id → tasks.id
        demo_ids = {t["id"] for t in demo_tasks}
        children = [t for t in demo_tasks if t.get("parent_id") in demo_ids]
        parents = [t for t in demo_tasks if t.get("parent_id") not in demo_ids]
        ordered = children + parents

        count = 0
        for task in ordered:
            deleted = db.delete_task(_db(), task["id"])
            if deleted:
                count += 1
        return jsonify({"deleted": count})

    return app


def main() -> None:
    app = create_app()
    port = int(os.environ.get("DEVBOARD_DASHBOARD_PORT", "4999"))
    host = os.environ.get("DEVBOARD_DASHBOARD_HOST", "127.0.0.1")
    log.info("Flask дашборд: http://%s:%d", host, port)
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()

"""Flask-дашборд малой команды devboard.

Запуск:
    cd /D.AI/команда/dashboard && uv run python app.py
    или через ../commands/devboard-start.sh

API — см. /D.AI/команда/детали_дашборда.md §API.
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

# Кириллица в пути ломает editable .pth — импортируем pride_tasks по абсолютному
# пути (паттерн из pride_mcp/server.py).
_MCP_DIR = Path(__file__).resolve().parent.parent / "mcp_server"
if str(_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_MCP_DIR))

# roles/ package lives at repo root — add it so `from roles.validator import ...` works
_REPO_ROOT_EARLY = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT_EARLY) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT_EARLY))

from flask import Flask, Response, jsonify, render_template, request  # noqa: E402

from pride_tasks import db, tools  # noqa: E402

logging.basicConfig(
    level=os.environ.get("PRIDE_DASHBOARD_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("pride_dashboard")

# === Пути ===

_REPO_ROOT = Path(__file__).resolve().parent.parent  # /D.AI/команда
_DATA_DIR = _REPO_ROOT / "data"
_ROLES_DIR = _REPO_ROOT / "roles"
_COMMANDS_DIR = _REPO_ROOT / "commands"
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

    # === MCP pride-tasks: интересные действия ===

    if name == "mcp__pride-tasks__create_task":
        title = _trim(inp.get("title", ""), 70)
        assignee = inp.get("assignee") or "не назначено"
        return f"📝  Создаёт задачу для {assignee}: «{title}»"

    if name == "mcp__pride-tasks__update_task":
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

    if name == "mcp__pride-tasks__claim_task":
        tid = (inp.get("task_id") or "")[:6]
        return f"🤝  Берёт задачу #{tid}"

    if name == "mcp__pride-tasks__add_comment":
        tid = (inp.get("task_id") or "")[:6]
        text = _trim(inp.get("text", ""), 80)
        return f"💬  Комментирует #{tid}: «{text}»"

    if name == "mcp__pride-tasks__submit_result":
        tid = (inp.get("task_id") or "")[:6]
        return f"📦  Сдаёт результат по #{tid}"

    if name == "mcp__pride-tasks__add_dependency":
        a = (inp.get("task_id") or "")[:6]
        b = (inp.get("depends_on") or "")[:6]
        return f"🔗  Связь: #{a} ждёт #{b}"

    if name == "mcp__pride-tasks__chat_post":
        # В чат — уже видно в правой панели, дублировать не надо
        return None

    if name == "mcp__pride-tasks__notify_dmitry":
        text = _trim(inp.get("text", ""), 80)
        return f"🔔  Telegram Дмитрию: «{text}»"

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
        "mcp__pride-tasks__list_tasks",
        "mcp__pride-tasks__get_task",
        "mcp__pride-tasks__chat_recent",
        "mcp__pride-tasks__get_dependencies",
        "mcp__pride-tasks__list_roles",
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
    забывает. Лучше авто-закрыть и попросить Дмитрия acceptance, чем
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
        from pride_tasks import tools as pt_tools
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


def _has_pending_work() -> bool:
    """Есть ли задачи в очереди тимлида? (todo + wip + needs_approval кроме destructive)."""
    try:
        for status in ("todo", "wip"):
            tasks = db.list_tasks(DB_PATH, status=status, assignee="тимлид", limit=20)
            if tasks:
                return True
        # needs_approval с assignee=тимлид (approved task ждут разморозки)
        approval_tasks = db.list_tasks(DB_PATH, status="needs_approval", assignee="тимлид", limit=20)
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


def _start_team_process(triggered_by: str = "user") -> dict[str, Any]:
    """Запустить subprocess тимлида.

    Выбор скрипта по платформе: на Windows — devboard-work.ps1 через
    powershell, на macOS/Linux — devboard-work.sh через bash.
    """

    with _team_state["lock"]:
        proc = _team_state["process"]
        if proc is not None and proc.poll() is None:
            return {"ok": False, "reason": "already_running", "pid": proc.pid}

        if sys.platform == "win32":
            work_script = _COMMANDS_DIR / "devboard-work.ps1"
            cmd = [
                "powershell",
                "-ExecutionPolicy",
                "Bypass",
                "-NoProfile",
                "-File",
                str(work_script),
            ]
        else:
            work_script = _COMMANDS_DIR / "devboard-work.sh"
            cmd = ["/bin/bash", str(work_script)]

        if not work_script.exists():
            return {"ok": False, "reason": "missing_script", "path": str(work_script)}

        new_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=str(_REPO_ROOT),
            env={**os.environ, "PRIDE_TASKS_DB": str(DB_PATH)},
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
        )
        t.start()
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

    # === Tasks ===

    @app.get("/api/tasks")
    def api_list_tasks() -> Any:
        status = request.args.get("status")
        assignee = request.args.get("assignee")
        label = request.args.get("label")
        limit = int(request.args.get("limit", 200))
        include_archived = request.args.get("archived") in ("1", "true", "yes")
        res = tools.list_tasks(
            status=status, assignee=assignee, label=label, limit=limit, db_path=_db()
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
        # Зеркалим комментарии Дмитрия в чат, чтобы тимлид (читающий только
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
          - assignee возвращается на reporter'а (создателя), чтобы при
            следующем list_tasks(assignee=тимлид) она попала к нему обратно.
        """
        existing = tools.get_task(task_id, db_path=_db())
        if existing["статус"] == "not_found":
            return jsonify(existing), 404
        reporter = existing["задача"].get("reporter") or "тимлид"
        upd = tools.update_task(
            task_id,
            status="todo",
            assignee=reporter,
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
        upd = tools.update_task(task_id, status="done", db_path=_db())
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
            return jsonify({"статус": "error", "причина": "depends_on пустой"}), 400
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
        result = tools.list_roles(db_path=_db())
        # Поднимаем поля capabilities.{llm,model,temperature,max_tokens,system_prompt}
        # на верхний уровень — фронт ждёт плоский формат (r.model и т.п.).
        for role in result.get("роли", []):
            caps = role.get("capabilities") or {}
            if isinstance(caps, dict):
                for key in ("llm", "model", "temperature", "max_tokens", "system_prompt"):
                    if key in caps and key not in role:
                        role[key] = caps[key]
        return jsonify(result)

    @app.post("/api/roles")
    def api_create_role() -> Any:
        data = request.get_json(silent=True) or {}
        name = (data.get("name") or "").strip()
        description = (data.get("description") or "").strip()
        if not name:
            return jsonify({"статус": "error", "причина": "name обязателен"}), 400
        import re as _re2
        if not _re2.match(r'^[a-z][a-z0-9-]{0,31}$', name):
            return jsonify({"статус": "error", "причина": "name должен быть slug ^[a-z][a-z0-9-]{1,32}$"}), 400
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
            return jsonify({"статус": "error", "причина": f"роль «{name}» уже существует"}), 409
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

        res = _start_team_process()
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
                    SUM(total_cost_usd) AS cost
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
        from pride_tasks import router
        return jsonify(router.pick_from_db(_db()))

    @app.get("/api/chat")
    def api_chat_list() -> Any:
        since = int(request.args.get("since", 0))
        limit = int(request.args.get("limit", 100))
        msgs = db.list_chat_messages(_db(), since=since, limit=limit)
        return jsonify({"messages": msgs})

    @app.post("/api/chat")
    def api_chat_post() -> Any:
        data = request.get_json(silent=True) or {}
        author = data.get("author", "пользователь")
        text = data.get("text", "")
        try:
            msg = db.post_chat_message(_db(), author, text)
        except ValueError as exc:
            return jsonify({"статус": "error", "причина": str(exc)}), 400
        return jsonify({"статус": "ok", "сообщение": msg}), 201

    @app.get("/api/inbox")
    def api_inbox() -> Any:
        """Что требует личного внимания Дмитрия.

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
        """
        approval_tasks = db.list_tasks(_db(), status="needs_approval", limit=200)
        review_tasks = db.list_tasks(_db(), status="review", limit=200)
        approval_ids = {t["id"] for t in approval_tasks}
        review_ids = {t["id"] for t in review_tasks}
        # questions: задачи назначенные Дмитрию, не попавшие в первые две группы.
        questions: list = []
        for t in db.list_tasks(_db(), assignee="пользователь", limit=200):
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

    @app.post("/api/open-folder")
    def api_open_folder() -> Any:
        """Открыть папку в системном файловом менеджере (macOS: Finder, Linux: xdg-open).

        Принимает {"path": "data/backups"} — относительный путь от repo root.
        Используется кнопкой «Открыть папку» на странице Settings.
        """
        data = request.get_json(silent=True) or {}
        rel_path = (data.get("path") or "").strip()
        if not rel_path:
            return jsonify({"статус": "error", "причина": "path обязателен"}), 400
        # Безопасность: разрешаем только data/ — не допускаем path traversal
        target = (_REPO_ROOT / rel_path).resolve()
        data_resolved = (_DATA_DIR).resolve()
        try:
            target.relative_to(data_resolved)
        except ValueError:
            return jsonify({"статус": "error", "причина": "доступ только к папке data/"}), 403
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
            return jsonify({"статус": "error", "причина": str(exc)}), 500
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

        # Epic: Build a landing page
        epic_res = tools.create_task(
            title="Build a landing page",
            description="Верстаем лендинг для продукта. Эпик-задача.",
            assignee="тимлид",
            reporter="пользователь",
            priority="P1",
            status="wip",
            labels=["demo"],
            db_path=_db(),
        )
        epic_id = epic_res["задача"]["id"]
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
            description="Деплой на продакшн — требует одобрения Дмитрия.",
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
    port = int(os.environ.get("PRIDE_DASHBOARD_PORT", "5000"))
    host = os.environ.get("PRIDE_DASHBOARD_HOST", "127.0.0.1")
    log.info("Flask дашборд: http://%s:%d", host, port)
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()

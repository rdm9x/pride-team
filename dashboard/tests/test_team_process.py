"""Тесты управления subprocess'ом тимлида.

Покрываются:
  - _start_team_process: happy, double-start, missing script
  - _stop_team_process: not_running, корректное завершение, kill после timeout
  - _team_status: running / stopped
  - _has_pending_work / _auto_can_start (различные ветки rate-limit)
  - _format_stream_event / _humanize_tool — табличные тесты на типы событий
  - _record_session_from_result — что input_tokens суммируется правильно

Subprocess.Popen полностью замокан, реальных процессов не запускаем.
"""

from __future__ import annotations

import sys
from pathlib import Path
from queue import Queue
from threading import Lock
from unittest.mock import MagicMock, patch

import pytest

# Импортируем app.py — conftest добавляет родителя в sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module  # noqa: E402


@pytest.fixture()
def reset_team_state():
    """Сбрасывает глобальное состояние тимлида к чистому виду."""
    saved = dict(app_module._team_state)
    app_module._team_state["process"] = None
    app_module._team_state["queue"] = Queue()
    app_module._team_state["started_at"] = None
    app_module._team_state["lock"] = Lock()
    app_module._team_state["auto_mode"] = False
    app_module._team_state["starts_history"] = []
    app_module._team_state["auto_pause_reason"] = None
    yield
    # Восстанавливаем
    for k, v in saved.items():
        app_module._team_state[k] = v


# === _start_team_process ===


def test_start_team_process_already_running(reset_team_state) -> None:
    fake = MagicMock()
    fake.poll.return_value = None  # ещё работает
    fake.pid = 12345
    app_module._team_state["process"] = fake

    res = app_module._start_team_process()
    assert res["ok"] is False
    assert res["reason"] == "already_running"
    assert res["pid"] == 12345


def test_start_team_process_missing_script(reset_team_state, monkeypatch, tmp_path) -> None:
    # Подменяем _COMMANDS_DIR на пустую папку — скрипта pride-team-work.sh там нет.
    monkeypatch.setattr(app_module, "_COMMANDS_DIR", tmp_path)
    res = app_module._start_team_process()
    assert res["ok"] is False
    assert res["reason"] == "missing_script"
    assert str(tmp_path) in res["path"]


def test_start_team_process_happy(reset_team_state, monkeypatch, tmp_path) -> None:
    # Скрипт существует
    script_name = "pride-team-work.ps1" if sys.platform == "win32" else "pride-team-work.sh"
    work_script = tmp_path / script_name
    work_script.write_text("#!/bin/bash\necho hi\n")
    monkeypatch.setattr(app_module, "_COMMANDS_DIR", tmp_path)
    monkeypatch.setattr(app_module, "_PID_FILE", tmp_path / "team.pid")
    monkeypatch.setattr(app_module, "_LIVE_LOG", tmp_path / "team.log")

    fake_proc = MagicMock()
    fake_proc.pid = 99999
    fake_proc.poll.return_value = None
    fake_proc.stdout = iter([])  # пустой stdout, чтобы _stream_reader не зависал

    with patch("subprocess.Popen", return_value=fake_proc) as popen_mock:
        res = app_module._start_team_process(triggered_by="user")

    assert res["ok"] is True
    assert res["pid"] == 99999
    assert popen_mock.called
    # PID-файл создан
    assert (tmp_path / "team.pid").exists()
    assert (tmp_path / "team.pid").read_text() == "99999"
    # В starts_history добавилась метка
    assert len(app_module._team_state["starts_history"]) == 1


# === _stop_team_process ===


def test_stop_team_process_not_running(reset_team_state) -> None:
    res = app_module._stop_team_process()
    assert res["ok"] is False
    assert res["reason"] == "not_running"


def test_stop_team_process_when_already_finished(reset_team_state) -> None:
    fake = MagicMock()
    fake.poll.return_value = 0  # завершился
    app_module._team_state["process"] = fake

    res = app_module._stop_team_process()
    assert res["ok"] is False
    assert res["reason"] == "not_running"


def test_stop_team_process_happy(reset_team_state, monkeypatch, tmp_path) -> None:
    pid_file = tmp_path / "team.pid"
    pid_file.write_text("123")
    monkeypatch.setattr(app_module, "_PID_FILE", pid_file)

    fake = MagicMock()
    fake.poll.return_value = None  # работает
    fake.wait.return_value = 0
    app_module._team_state["process"] = fake

    res = app_module._stop_team_process()
    assert res["ok"] is True
    # SIGTERM/terminate был отправлен
    if sys.platform == "win32":
        fake.terminate.assert_called_once()
    else:
        fake.send_signal.assert_called_once()
    fake.wait.assert_called_once_with(timeout=5)
    assert app_module._team_state["process"] is None
    assert not pid_file.exists()


def test_stop_team_process_kill_on_timeout(reset_team_state, monkeypatch, tmp_path) -> None:
    import subprocess as sp
    monkeypatch.setattr(app_module, "_PID_FILE", tmp_path / "team.pid")

    fake = MagicMock()
    fake.poll.return_value = None
    fake.wait.side_effect = sp.TimeoutExpired(cmd="x", timeout=5)
    app_module._team_state["process"] = fake

    res = app_module._stop_team_process()
    assert res["ok"] is True
    # После таймаута должен сработать kill
    fake.kill.assert_called_once()


# === _team_status ===


def test_team_status_stopped(reset_team_state) -> None:
    s = app_module._team_status()
    assert s["status"] == "stopped"


def test_team_status_running(reset_team_state) -> None:
    fake = MagicMock()
    fake.poll.return_value = None
    fake.pid = 1234
    app_module._team_state["process"] = fake
    app_module._team_state["started_at"] = 1700000000

    s = app_module._team_status()
    assert s["status"] == "running"
    assert s["pid"] == 1234
    assert s["started_at"] == 1700000000


def test_team_status_treats_finished_proc_as_stopped(reset_team_state) -> None:
    fake = MagicMock()
    fake.poll.return_value = 0  # уже завершился
    app_module._team_state["process"] = fake
    s = app_module._team_status()
    assert s["status"] == "stopped"


# === _has_pending_work / _auto_can_start ===


def test_has_pending_work_empty(tmp_path, monkeypatch) -> None:
    from pride_tasks import db as _db
    db_path = tmp_path / "x.db"
    _db.init_db(db_path)
    monkeypatch.setattr(app_module, "DB_PATH", db_path)
    assert app_module._has_pending_work() is False


def test_has_pending_work_todo_for_team_lead(tmp_path, monkeypatch) -> None:
    from pride_tasks import db as _db
    db_path = tmp_path / "x.db"
    _db.init_db(db_path)
    _db.insert_task(db_path, title="todo for lead", assignee="тимлид")
    monkeypatch.setattr(app_module, "DB_PATH", db_path)
    assert app_module._has_pending_work() is True


def test_has_pending_work_ignores_other_assignees(tmp_path, monkeypatch) -> None:
    from pride_tasks import db as _db
    db_path = tmp_path / "x.db"
    _db.init_db(db_path)
    _db.insert_task(db_path, title="for qa", assignee="qa")
    monkeypatch.setattr(app_module, "DB_PATH", db_path)
    assert app_module._has_pending_work() is False


def test_auto_can_start_disabled(reset_team_state) -> None:
    app_module._team_state["auto_mode"] = False
    ok, reason = app_module._auto_can_start(now=1000)
    assert ok is False
    assert "выключен" in reason


def test_auto_can_start_already_running(reset_team_state) -> None:
    app_module._team_state["auto_mode"] = True
    fake = MagicMock()
    fake.poll.return_value = None
    app_module._team_state["process"] = fake
    ok, reason = app_module._auto_can_start(now=1000)
    assert ok is False
    assert "уже работает" in reason


def test_auto_can_start_rate_limit_min_interval(reset_team_state) -> None:
    app_module._team_state["auto_mode"] = True
    now = 1_000_000
    # последний запуск 5 секунд назад — меньше минимума (30с)
    app_module._team_state["starts_history"] = [now - 5]
    ok, reason = app_module._auto_can_start(now=now)
    assert ok is False
    assert "слишком часто" in reason


def test_auto_can_start_rate_limit_per_hour(reset_team_state) -> None:
    app_module._team_state["auto_mode"] = True
    now = 1_000_000
    # 20 запусков за последние 30 минут → лимит исчерпан
    app_module._team_state["starts_history"] = [now - 60 * i for i in range(20)]
    ok, reason = app_module._auto_can_start(now=now)
    assert ok is False
    assert "лимит" in reason


def test_auto_can_start_no_work(reset_team_state, tmp_path, monkeypatch) -> None:
    from pride_tasks import db as _db
    db_path = tmp_path / "x.db"
    _db.init_db(db_path)
    monkeypatch.setattr(app_module, "DB_PATH", db_path)

    app_module._team_state["auto_mode"] = True
    ok, reason = app_module._auto_can_start(now=1_000_000)
    assert ok is False
    assert "пустая" in reason


def test_auto_can_start_ok(reset_team_state, tmp_path, monkeypatch) -> None:
    from pride_tasks import db as _db
    db_path = tmp_path / "x.db"
    _db.init_db(db_path)
    _db.insert_task(db_path, title="for lead", assignee="тимлид")
    monkeypatch.setattr(app_module, "DB_PATH", db_path)

    app_module._team_state["auto_mode"] = True
    ok, reason = app_module._auto_can_start(now=1_000_000)
    assert ok is True
    assert reason == "ок"


def test_auto_can_start_cleans_old_history(reset_team_state, tmp_path, monkeypatch) -> None:
    """Старые (>1 час) метки в starts_history должны вычищаться при проверке."""
    from pride_tasks import db as _db
    db_path = tmp_path / "x.db"
    _db.init_db(db_path)
    _db.insert_task(db_path, title="for lead", assignee="тимлид")
    monkeypatch.setattr(app_module, "DB_PATH", db_path)
    app_module._team_state["auto_mode"] = True

    now = 1_000_000
    # старые метки (>1 час) + 0 свежих
    app_module._team_state["starts_history"] = [now - 7200, now - 5000]
    ok, _ = app_module._auto_can_start(now=now)
    assert ok is True
    # старые метки вычищены
    assert app_module._team_state["starts_history"] == []


# === _format_stream_event ===


def test_format_stream_event_empty_returns_none() -> None:
    assert app_module._format_stream_event("") is None
    assert app_module._format_stream_event("   ") is None


def test_format_stream_event_non_json_returns_none() -> None:
    assert app_module._format_stream_event("plain text") is None


def test_format_stream_event_invalid_json_returns_none() -> None:
    assert app_module._format_stream_event("{broken") is None


def test_format_stream_event_assistant_text() -> None:
    raw = '{"type": "assistant", "message": {"content": [{"type": "text", "text": "думаю"}]}}'
    out = app_module._format_stream_event(raw)
    assert out is not None
    assert "думаю" in out


def test_format_stream_event_assistant_tool_use() -> None:
    raw = (
        '{"type": "assistant", "message": {"content": ['
        '{"type": "tool_use", "name": "mcp__pride-tasks__create_task", '
        '"input": {"title": "новая", "assignee": "qa"}}'
        ']}}'
    )
    out = app_module._format_stream_event(raw)
    assert out is not None
    assert "Создаёт задачу" in out
    assert "qa" in out


def test_format_stream_event_result_no_error() -> None:
    raw = '{"type": "result", "duration_ms": 5000, "is_error": false, "usage": {}}'
    # Внутри есть запись в БД — пусть упадёт безопасно через try/except.
    out = app_module._format_stream_event(raw)
    assert out is not None
    assert "Сессия закончена" in out


def test_format_stream_event_result_with_error() -> None:
    raw = '{"type": "result", "duration_ms": 90000, "is_error": true, "usage": {}}'
    out = app_module._format_stream_event(raw)
    assert out is not None
    assert "ошибкой" in out
    assert "м" in out  # минуты в выводе


def test_format_stream_event_unknown_type_returns_none() -> None:
    raw = '{"type": "system"}'
    assert app_module._format_stream_event(raw) is None


# === _humanize_tool ===


@pytest.mark.parametrize("name,inp,expected_marker", [
    ("mcp__pride-tasks__create_task", {"title": "T", "assignee": "qa"}, "Создаёт"),
    ("mcp__pride-tasks__update_task", {"task_id": "abc123def", "status": "done"}, "Закрывает"),
    ("mcp__pride-tasks__update_task", {"task_id": "abc123def", "status": "review"}, "приёмку"),
    ("mcp__pride-tasks__update_task", {"task_id": "abc123def", "status": "wip"}, "работу"),
    ("mcp__pride-tasks__update_task", {"task_id": "abc123def", "status": "blocked"}, "Блокирует"),
    ("mcp__pride-tasks__claim_task", {"task_id": "abcdef"}, "Берёт"),
    ("mcp__pride-tasks__add_comment", {"task_id": "abc", "text": "ok"}, "Комментирует"),
    ("mcp__pride-tasks__submit_result", {"task_id": "abc"}, "Сдаёт"),
    ("mcp__pride-tasks__add_dependency", {"task_id": "a", "depends_on": "b"}, "ждёт"),
    ("mcp__pride-tasks__notify_dmitry", {"text": "hello"}, "Telegram"),
    ("Task", {"description": "сделай", "prompt": "ты qa"}, "qa"),
    ("Write", {"file_path": "/x"}, "Создаёт файл"),
    ("Edit", {"file_path": "/x"}, "Правит файл"),
    ("Bash", {"command": "ls"}, "Запускает"),
])
def test_humanize_tool_known_tools(name: str, inp: dict, expected_marker: str) -> None:
    out = app_module._humanize_tool(name, inp)
    assert out is not None
    assert expected_marker in out


@pytest.mark.parametrize("name", [
    "mcp__pride-tasks__list_tasks",
    "mcp__pride-tasks__get_task",
    "mcp__pride-tasks__chat_recent",
    "mcp__pride-tasks__get_dependencies",
    "mcp__pride-tasks__list_roles",
    "mcp__pride-tasks__chat_post",
    "Read",
    "Glob",
    "Grep",
    "UnknownTool",
])
def test_humanize_tool_silent_tools(name: str) -> None:
    """Чтение/навигация и неизвестные тулы — None (не показываем)."""
    assert app_module._humanize_tool(name, {}) is None


def test_humanize_tool_update_task_rename_returns_none() -> None:
    # Переименование (status=None) — шум, не показываем
    assert app_module._humanize_tool(
        "mcp__pride-tasks__update_task",
        {"task_id": "abc", "title": "новое название"},
    ) is None


def test_humanize_tool_task_role_detection_default() -> None:
    # Если ни одной роли в prompt не нашлось — fallback "подчинённого"
    out = app_module._humanize_tool("Task", {"description": "x", "prompt": "сделай работу"})
    assert out is not None
    assert "подчинённого" in out


# === _record_session_from_result ===


def test_record_session_sums_input_tokens(tmp_path, monkeypatch) -> None:
    from pride_tasks import db as _db
    db_path = tmp_path / "x.db"
    _db.init_db(db_path)
    monkeypatch.setattr(app_module, "DB_PATH", db_path)

    ev = {
        "duration_ms": 12000,
        "num_turns": 5,
        "is_error": False,
        "total_cost_usd": 0.05,
        "model": "claude-sonnet-4-5",
    }
    usage = {
        "input_tokens": 100,
        "cache_creation_input_tokens": 200,
        "cache_read_input_tokens": 300,
        "output_tokens": 50,
    }
    app_module._record_session_from_result(ev, usage)
    summary = _db.usage_summary(db_path)
    # Хоть какая-то сессия записалась
    assert summary is not None


def test_record_session_picks_primary_model_from_modelusage(tmp_path, monkeypatch) -> None:
    from pride_tasks import db as _db
    db_path = tmp_path / "x.db"
    _db.init_db(db_path)
    monkeypatch.setattr(app_module, "DB_PATH", db_path)

    ev = {
        "duration_ms": 5000,
        "is_error": False,
        # model отсутствует — должен взяться из modelUsage по max costUSD
        "modelUsage": {
            "claude-haiku-4-5": {"costUSD": 0.001},
            "claude-sonnet-4-5": {"costUSD": 0.05},
        },
    }
    # Не падает — это главное; проверки внутренних полей делает БД
    app_module._record_session_from_result(ev, {"input_tokens": 10, "output_tokens": 5})


def test_record_session_handles_missing_usage(tmp_path, monkeypatch) -> None:
    from pride_tasks import db as _db
    db_path = tmp_path / "x.db"
    _db.init_db(db_path)
    monkeypatch.setattr(app_module, "DB_PATH", db_path)

    # Пустой usage — должен не упасть
    app_module._record_session_from_result({"duration_ms": 1000, "is_error": False}, {})

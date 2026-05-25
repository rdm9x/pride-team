"""Тесты B5 (1.6): model_hint per-task — реальная инжекция в subagent.

Покрывает:
  1. pick_model_for_role() — корректный выбор модели по hint-задачам роли в БД.
  2. build_claude_command() — PRIDE_TEAM_MODEL env-var содержит нужный alias.
  3. _start_team_process() — subprocess получает PRIDE_TEAM_MODEL из env (интеграция).
  4. Правило ранга: haiku + пустые → haiku wins; opus beat sonnet beat haiku.
  5. Пустая очередь → haiku (дефолт роутера).
  6. Смешанная очередь: haiku + без hint → haiku wins (hint beats default).

Реальный claude не запускается — subprocess.Popen замокан.
"""

from __future__ import annotations

import sys
from pathlib import Path
from queue import Queue
from threading import Lock
from unittest.mock import MagicMock, patch

import pytest

# === Пути ===
_REPO_ROOT = Path(__file__).resolve().parent.parent
_DASHBOARD_DIR = _REPO_ROOT / "dashboard"
_MCP_DIR = _REPO_ROOT / "mcp_server"

if str(_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_MCP_DIR))
if str(_DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD_DIR))

from pride_tasks import db as db_mod  # noqa: E402

import app as app_module  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Вспомогательные утилиты
# ─────────────────────────────────────────────────────────────────────────────

def _init_db(tmp_path: Path) -> Path:
    """Создать и инициализировать временную БД."""
    path = tmp_path / "tasks.db"
    db_mod.init_db(path)
    return path


def _create_task(db_path: Path, *, assignee: str, model_hint: str | None = None,
                 status: str = "todo", title: str = "задача") -> str:
    """Создать задачу в БД, вернуть id."""
    task = db_mod.insert_task(
        db_path,
        title=title,
        description="",
        assignee=assignee,
        status=status,
        model_hint=model_hint,
    )
    return task["id"]


def _make_fake_proc() -> MagicMock:
    fake = MagicMock()
    fake.pid = 99999
    fake.poll.return_value = None
    fake.stdout = iter([])
    return fake


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
    app_module._team_state["reader_thread"] = None
    yield
    for k, v in saved.items():
        app_module._team_state[k] = v


# ─────────────────────────────────────────────────────────────────────────────
# 1. pick_model_for_role() — выбор модели по hint задач роли
# ─────────────────────────────────────────────────────────────────────────────

def test_pick_model_for_role_haiku(tmp_path: Path) -> None:
    """Единственная задача с model_hint='haiku' → alias='haiku'."""
    db_path = _init_db(tmp_path)
    _create_task(db_path, assignee="dev-lead", model_hint="haiku")

    alias = app_module.pick_model_for_role("dev-lead", db_path=db_path)
    assert alias == "haiku", f"ожидали haiku, получили {alias!r}"


def test_pick_model_for_role_opus_wins(tmp_path: Path) -> None:
    """opus имеет наивысший ранг среди hint: opus beats sonnet/haiku."""
    db_path = _init_db(tmp_path)
    _create_task(db_path, assignee="dev-lead", model_hint="haiku", title="haiku-задача")
    _create_task(db_path, assignee="dev-lead", model_hint="opus", title="opus-задача")
    _create_task(db_path, assignee="dev-lead", model_hint="sonnet", title="sonnet-задача")

    alias = app_module.pick_model_for_role("dev-lead", db_path=db_path)
    assert alias == "opus", f"opus должен победить, получили {alias!r}"


def test_pick_model_for_role_sonnet_no_opus(tmp_path: Path) -> None:
    """sonnet beats haiku, когда нет opus."""
    db_path = _init_db(tmp_path)
    _create_task(db_path, assignee="dev-lead", model_hint="haiku", title="haiku-задача")
    _create_task(db_path, assignee="dev-lead", model_hint="sonnet", title="sonnet-задача")

    alias = app_module.pick_model_for_role("dev-lead", db_path=db_path)
    assert alias == "sonnet", f"sonnet должен победить haiku, получили {alias!r}"


def test_pick_model_for_role_empty_queue_returns_haiku(tmp_path: Path) -> None:
    """Пустая очередь → router возвращает haiku (нет задач → Haiku хватит)."""
    db_path = _init_db(tmp_path)

    alias = app_module.pick_model_for_role("dev-lead", db_path=db_path)
    assert alias == "haiku", f"при пустой очереди ожидаем haiku, получили {alias!r}"


def test_pick_model_for_role_no_hint_uses_label_logic(tmp_path: Path) -> None:
    """Задачи без hint → роутер использует label-логику (sonnet для обычных задач)."""
    db_path = _init_db(tmp_path)
    _create_task(db_path, assignee="dev-lead", model_hint=None, title="обычная задача")

    alias = app_module.pick_model_for_role("dev-lead", db_path=db_path)
    assert alias == "sonnet", f"для обычной задачи без hint ожидаем sonnet, получили {alias!r}"


def test_pick_model_for_role_haiku_plus_no_hint_haiku_wins(tmp_path: Path) -> None:
    """Смешанная очередь: 1 задача с hint='haiku' + 1 без hint → haiku wins.

    Hint явного пользователя (haiku) имеет приоритет над label-дефолтом (sonnet).
    """
    db_path = _init_db(tmp_path)
    _create_task(db_path, assignee="dev-lead", model_hint="haiku", title="с hint")
    _create_task(db_path, assignee="dev-lead", model_hint=None, title="без hint")

    alias = app_module.pick_model_for_role("dev-lead", db_path=db_path)
    assert alias == "haiku", (
        f"haiku hint должен победить дефолтный sonnet, получили {alias!r}"
    )


def test_pick_model_for_role_ignores_other_roles(tmp_path: Path) -> None:
    """Задачи других ролей не влияют на выбор модели для dev-lead."""
    db_path = _init_db(tmp_path)
    # opus у другой роли — не должна влиять
    _create_task(db_path, assignee="marketing-lead", model_hint="opus", title="чужая opus")
    # dev-lead имеет только haiku
    _create_task(db_path, assignee="dev-lead", model_hint="haiku", title="своя haiku")

    alias = app_module.pick_model_for_role("dev-lead", db_path=db_path)
    assert alias == "haiku", (
        f"opus другой роли не должен влиять на dev-lead, получили {alias!r}"
    )


def test_pick_model_for_role_ignores_non_todo_status(tmp_path: Path) -> None:
    """Задачи в статусе wip/review/done не учитываются — только todo."""
    db_path = _init_db(tmp_path)
    # opus задача в wip — не todo, не должна учитываться
    _create_task(db_path, assignee="dev-lead", model_hint="opus", status="wip", title="wip-opus")
    # haiku задача в todo
    _create_task(db_path, assignee="dev-lead", model_hint="haiku", status="todo", title="todo-haiku")

    alias = app_module.pick_model_for_role("dev-lead", db_path=db_path)
    assert alias == "haiku", (
        f"wip-задача с opus не должна учитываться, ожидаем haiku, получили {alias!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. build_claude_command() — PRIDE_TEAM_MODEL в env
# ─────────────────────────────────────────────────────────────────────────────

def test_build_claude_command_haiku_env(tmp_path: Path) -> None:
    """build_claude_command() должен вернуть PRIDE_TEAM_MODEL=haiku для роли с haiku-задачей."""
    if sys.platform == "win32":
        pytest.skip("Unix-only path test")

    db_path = _init_db(tmp_path)
    _create_task(db_path, assignee="dev-lead", model_hint="haiku")

    # Создаём заглушку скрипта
    work_script = tmp_path / "devboard-work.sh"
    work_script.write_text("#!/bin/bash\necho hi\n")

    cmd, extra_env, script = app_module.build_claude_command(
        "dev-lead",
        db_path=db_path,
        commands_dir=tmp_path,
    )

    assert extra_env["PRIDE_TEAM_MODEL"] == "haiku", (
        f"ожидали PRIDE_TEAM_MODEL=haiku, получили {extra_env['PRIDE_TEAM_MODEL']!r}"
    )
    assert "--role" in cmd
    assert "dev-lead" in cmd


def test_build_claude_command_opus_env(tmp_path: Path) -> None:
    """build_claude_command() должен вернуть PRIDE_TEAM_MODEL=opus когда есть opus-задача."""
    if sys.platform == "win32":
        pytest.skip("Unix-only path test")

    db_path = _init_db(tmp_path)
    _create_task(db_path, assignee="dev-lead", model_hint="opus")

    work_script = tmp_path / "devboard-work.sh"
    work_script.write_text("#!/bin/bash\necho hi\n")

    cmd, extra_env, _ = app_module.build_claude_command(
        "dev-lead",
        db_path=db_path,
        commands_dir=tmp_path,
    )

    assert extra_env["PRIDE_TEAM_MODEL"] == "opus"


def test_build_claude_command_managing_director(tmp_path: Path) -> None:
    """managing-director → devboard-managing.sh + PRIDE_TEAM_MODEL в env."""
    if sys.platform == "win32":
        pytest.skip("Unix-only path test")

    db_path = _init_db(tmp_path)

    managing_script = tmp_path / "devboard-managing.sh"
    managing_script.write_text("#!/bin/bash\necho managing\n")

    cmd, extra_env, script = app_module.build_claude_command(
        "managing-director",
        db_path=db_path,
        commands_dir=tmp_path,
    )

    assert str(managing_script) in cmd
    assert "--role" not in cmd
    assert "PRIDE_TEAM_MODEL" in extra_env


# ─────────────────────────────────────────────────────────────────────────────
# 3. _start_team_process() — subprocess получает PRIDE_TEAM_MODEL через env
# ─────────────────────────────────────────────────────────────────────────────

def test_start_team_process_env_contains_model_hint(
    reset_team_state, monkeypatch, tmp_path: Path
) -> None:
    """_start_team_process() инжектирует PRIDE_TEAM_MODEL=haiku в env subprocess."""
    if sys.platform == "win32":
        pytest.skip("Unix-only path test")

    db_path = _init_db(tmp_path)
    _create_task(db_path, assignee="dev-lead", model_hint="haiku")

    work_script = tmp_path / "devboard-work.sh"
    work_script.write_text("#!/bin/bash\necho hi\n")

    monkeypatch.setattr(app_module, "_COMMANDS_DIR", tmp_path)
    monkeypatch.setattr(app_module, "_PID_FILE", tmp_path / "team.pid")
    monkeypatch.setattr(app_module, "_LIVE_LOG", tmp_path / "team.log")
    monkeypatch.setattr(app_module, "DB_PATH", db_path)

    fake_proc = _make_fake_proc()

    with patch("subprocess.Popen", return_value=fake_proc) as popen_mock:
        res = app_module._start_team_process(role="dev-lead")

    assert res["ok"] is True

    called_env = popen_mock.call_args[1]["env"]
    assert "PRIDE_TEAM_MODEL" in called_env, "PRIDE_TEAM_MODEL должен быть в env subprocess"
    assert called_env["PRIDE_TEAM_MODEL"] == "haiku", (
        f"ожидали PRIDE_TEAM_MODEL=haiku, получили {called_env['PRIDE_TEAM_MODEL']!r}"
    )


def test_start_team_process_env_model_empty_queue(
    reset_team_state, monkeypatch, tmp_path: Path
) -> None:
    """Пустая очередь → PRIDE_TEAM_MODEL=haiku (router default для пустой очереди)."""
    if sys.platform == "win32":
        pytest.skip("Unix-only path test")

    db_path = _init_db(tmp_path)

    work_script = tmp_path / "devboard-work.sh"
    work_script.write_text("#!/bin/bash\necho hi\n")

    monkeypatch.setattr(app_module, "_COMMANDS_DIR", tmp_path)
    monkeypatch.setattr(app_module, "_PID_FILE", tmp_path / "team.pid")
    monkeypatch.setattr(app_module, "_LIVE_LOG", tmp_path / "team.log")
    monkeypatch.setattr(app_module, "DB_PATH", db_path)

    fake_proc = _make_fake_proc()

    with patch("subprocess.Popen", return_value=fake_proc) as popen_mock:
        res = app_module._start_team_process(role="dev-lead")

    assert res["ok"] is True

    called_env = popen_mock.call_args[1]["env"]
    assert called_env["PRIDE_TEAM_MODEL"] == "haiku"

"""Тесты B1 (1.5): /api/team/start — параметр role + backend подбор скрипта.

Покрываются:
  1. POST с {'role': 'marketing-lead'} → вызывается devboard-work.sh --role marketing-lead
  2. POST с {'role': 'managing-director'} → вызывается devboard-managing.sh
  3. POST без body → default managing-director → вызывается devboard-managing.sh

Subprocess.Popen полностью замокан, реальных процессов не запускаем.
"""

from __future__ import annotations

import sys
from pathlib import Path
from queue import Queue
from threading import Lock
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module  # noqa: E402


@pytest.fixture()
def reset_team_state():
    """Сбрасывает глобальное состояние всех ролей к чистому виду.

    D38BCDDA9CF9: обновлено для работы с _team_states[role] вместо _team_state.
    """
    saved_states = dict(app_module._team_states)
    saved_global = dict(app_module._global_state)

    app_module._team_states.clear()
    app_module._global_state["auto_mode"] = False
    app_module._global_state["auto_pause_reason"] = None

    yield

    app_module._team_states.clear()
    app_module._team_states.update(saved_states)
    app_module._global_state.clear()
    app_module._global_state.update(saved_global)


def _make_fake_proc():
    fake = MagicMock()
    fake.pid = 77777
    fake.poll.return_value = None
    fake.stdout = iter([])
    return fake


# ─────────────────────────────────────────────────────────────────────────────
# 1. POST {'role': 'marketing-lead'} → devboard-work.sh --role marketing-lead
# ─────────────────────────────────────────────────────────────────────────────

def test_start_role_marketing_lead_calls_work_script(
    reset_team_state, monkeypatch, tmp_path
) -> None:
    """role=marketing-lead должен вызвать devboard-work.sh с --role marketing-lead."""
    if sys.platform == "win32":
        pytest.skip("Unix-only path test")

    # Создаём devboard-work.sh в tmp_path (devboard-managing.sh намеренно отсутствует)
    work_script = tmp_path / "devboard-work.sh"
    work_script.write_text("#!/bin/bash\necho hi\n")
    monkeypatch.setattr(app_module, "_COMMANDS_DIR", tmp_path)
    monkeypatch.setattr(app_module, "_PID_FILE", tmp_path / "team.pid")
    monkeypatch.setattr(app_module, "_LIVE_LOG", tmp_path / "team.log")

    fake_proc = _make_fake_proc()

    with patch("subprocess.Popen", return_value=fake_proc) as popen_mock:
        res = app_module._start_team_process(role="marketing-lead")

    assert res["ok"] is True
    assert res["pid"] == 77777

    called_cmd = popen_mock.call_args[0][0]
    assert str(work_script) in called_cmd
    assert "--role" in called_cmd
    assert "marketing-lead" in called_cmd


# ─────────────────────────────────────────────────────────────────────────────
# 2. POST {'role': 'managing-director'} → devboard-managing.sh
# ─────────────────────────────────────────────────────────────────────────────

def test_start_role_managing_director_calls_managing_script(
    reset_team_state, monkeypatch, tmp_path
) -> None:
    """role=managing-director должен вызвать devboard-managing.sh."""
    if sys.platform == "win32":
        pytest.skip("Unix-only path test")

    managing_script = tmp_path / "devboard-managing.sh"
    managing_script.write_text("#!/bin/bash\necho managing\n")
    monkeypatch.setattr(app_module, "_COMMANDS_DIR", tmp_path)
    monkeypatch.setattr(app_module, "_PID_FILE", tmp_path / "team.pid")
    monkeypatch.setattr(app_module, "_LIVE_LOG", tmp_path / "team.log")

    fake_proc = _make_fake_proc()

    with patch("subprocess.Popen", return_value=fake_proc) as popen_mock:
        res = app_module._start_team_process(role="managing-director")

    assert res["ok"] is True
    assert res["pid"] == 77777

    called_cmd = popen_mock.call_args[0][0]
    assert str(managing_script) in called_cmd
    # --role НЕ должен передаваться Управляющему
    assert "--role" not in called_cmd


# ─────────────────────────────────────────────────────────────────────────────
# 3. POST без body → default managing-director → devboard-managing.sh
# ─────────────────────────────────────────────────────────────────────────────

def test_api_team_start_no_body_defaults_to_managing_director(
    monkeypatch, tmp_path
) -> None:
    """POST /api/team/start без body должен использовать role=managing-director."""
    if sys.platform == "win32":
        pytest.skip("Unix-only path test")

    from app import create_app  # type: ignore

    db = tmp_path / "tasks.db"
    flask_app = create_app(db_path=db)
    flask_app.config["TESTING"] = True

    # Создаём devboard-managing.sh в tmp_path
    managing_script = tmp_path / "devboard-managing.sh"
    managing_script.write_text("#!/bin/bash\necho managing\n")
    monkeypatch.setattr(app_module, "_COMMANDS_DIR", tmp_path)
    monkeypatch.setattr(app_module, "_PID_FILE", tmp_path / "team.pid")
    monkeypatch.setattr(app_module, "_LIVE_LOG", tmp_path / "team.log")

    # Сбрасываем состояние (D38BCDDA9CF9: новая структура)
    app_module._team_states.clear()
    app_module._global_state["auto_mode"] = False
    app_module._global_state["auto_pause_reason"] = None

    fake_proc = _make_fake_proc()

    with patch("subprocess.Popen", return_value=fake_proc) as popen_mock:
        with flask_app.test_client() as client:
            # POST без Content-Type и без тела
            resp = client.post("/api/team/start")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["статус"] == "ok"

    called_cmd = popen_mock.call_args[0][0]
    assert str(managing_script) in called_cmd
    assert "--role" not in called_cmd

"""Тесты Flask-API управления тимлидом и не покрытых endpoints.

Покрывают:
  - /api/team/start, /api/team/stop, /api/team/status (с мокированным subprocess)
  - /api/team/auto
  - /api/team/silence
  - /api/router/pick
  - /api/chat GET и POST (включая валидацию пустого автора)
  - /api/inbox (все три ветки: approvals, reviews, questions)
  - /api/usage
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
def reset_state():
    """Сбрасывает глобальное состояние тимлида (как в test_team_process)."""
    saved = dict(app_module._team_state)
    app_module._team_state["process"] = None
    app_module._team_state["queue"] = Queue()
    app_module._team_state["started_at"] = None
    app_module._team_state["lock"] = Lock()
    app_module._team_state["auto_mode"] = False
    app_module._team_state["starts_history"] = []
    app_module._team_state["auto_pause_reason"] = None
    yield
    for k, v in saved.items():
        app_module._team_state[k] = v


# === /api/team/status ===


def test_api_team_status_stopped(client, reset_state) -> None:
    r = client.get("/api/team/status")
    assert r.status_code == 200
    j = r.get_json()
    assert j["status"] == "stopped"
    assert j["auto_mode"] is False
    assert j["starts_last_hour"] == 0
    assert j["auto_pause_reason"] is None


def test_api_team_status_running(client, reset_state) -> None:
    fake = MagicMock()
    fake.poll.return_value = None
    fake.pid = 5555
    app_module._team_state["process"] = fake
    app_module._team_state["started_at"] = 1700000000

    r = client.get("/api/team/status")
    j = r.get_json()
    assert j["status"] == "running"
    assert j["pid"] == 5555


# === /api/team/start ===


def test_api_team_start_already_running(client, reset_state) -> None:
    fake = MagicMock()
    fake.poll.return_value = None
    fake.pid = 12345
    app_module._team_state["process"] = fake
    r = client.post("/api/team/start")
    assert r.status_code == 409
    assert r.get_json()["reason"] == "already_running"


def test_api_team_start_missing_script(client, reset_state, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(app_module, "_COMMANDS_DIR", tmp_path)
    r = client.post("/api/team/start")
    assert r.status_code == 409
    assert r.get_json()["reason"] == "missing_script"


def test_api_team_start_happy(client, reset_state, monkeypatch, tmp_path) -> None:
    script_name = "pride-team-work.ps1" if sys.platform == "win32" else "pride-team-work.sh"
    work_script = tmp_path / script_name
    work_script.write_text("#!/bin/bash\n")
    monkeypatch.setattr(app_module, "_COMMANDS_DIR", tmp_path)
    monkeypatch.setattr(app_module, "_PID_FILE", tmp_path / "team.pid")
    monkeypatch.setattr(app_module, "_LIVE_LOG", tmp_path / "team.log")

    fake = MagicMock()
    fake.pid = 4242
    fake.poll.return_value = None
    fake.stdout = iter([])

    with patch("subprocess.Popen", return_value=fake):
        r = client.post("/api/team/start")
    assert r.status_code == 200
    assert r.get_json()["pid"] == 4242


# === /api/team/stop ===


def test_api_team_stop_not_running(client, reset_state) -> None:
    r = client.post("/api/team/stop")
    assert r.status_code == 409
    assert r.get_json()["reason"] == "not_running"


def test_api_team_stop_happy(client, reset_state, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(app_module, "_PID_FILE", tmp_path / "team.pid")
    fake = MagicMock()
    fake.poll.return_value = None
    fake.wait.return_value = 0
    app_module._team_state["process"] = fake
    r = client.post("/api/team/stop")
    assert r.status_code == 200
    assert r.get_json()["статус"] == "ok"


# === /api/team/auto ===


def test_api_team_auto_enable(client, reset_state) -> None:
    r = client.post("/api/team/auto", json={"enabled": True})
    assert r.status_code == 200
    j = r.get_json()
    assert j["auto_mode"] is True
    assert app_module._team_state["auto_mode"] is True


def test_api_team_auto_disable_clears_pause_reason(client, reset_state) -> None:
    app_module._team_state["auto_pause_reason"] = "something"
    r = client.post("/api/team/auto", json={"enabled": False})
    assert r.status_code == 200
    j = r.get_json()
    assert j["auto_mode"] is False
    assert app_module._team_state["auto_pause_reason"] is None


def test_api_team_auto_default_disabled(client, reset_state) -> None:
    r = client.post("/api/team/auto", json={})
    j = r.get_json()
    assert j["auto_mode"] is False


# === /api/team/silence ===


def test_api_team_silence_no_sessions(client, reset_state) -> None:
    r = client.get("/api/team/silence")
    assert r.status_code == 200
    j = r.get_json()
    assert j["silent"] is False
    assert "ещё не было" in j["reason"]


def test_api_team_silence_recent_session(client, reset_state) -> None:
    """Сессия завершилась только что — silent=False."""
    from pride_tasks import db as _db
    import time as _t
    db_path = Path(client.application.config["DB_PATH"])
    now = int(_t.time())
    _db.record_claude_session(
        db_path, started_at=now - 30, finished_at=now,
        duration_ms=30000, num_turns=1, input_tokens=10, output_tokens=5,
        total_cost_usd=0.01, model="sonnet", is_error=False,
    )
    r = client.get("/api/team/silence")
    j = r.get_json()
    assert j["silent"] is False


def test_api_team_silence_stale_session(client, reset_state) -> None:
    """Сессия 10 мин назад без chat-сообщения тимлида — silent=True."""
    from pride_tasks import db as _db
    db_path = Path(client.application.config["DB_PATH"])
    long_ago = 1_700_000_000  # давно
    _db.record_claude_session(
        db_path, started_at=long_ago - 60, finished_at=long_ago,
        duration_ms=60000, num_turns=1, input_tokens=10, output_tokens=5,
        total_cost_usd=0.01, model="sonnet", is_error=False,
    )
    r = client.get("/api/team/silence")
    j = r.get_json()
    assert j["silent"] is True
    assert j["since_session_min"] >= 1


def test_api_team_silence_lead_replied(client, reset_state) -> None:
    """Тимлид отписался в чат после сессии — silent=False."""
    from pride_tasks import db as _db
    db_path = Path(client.application.config["DB_PATH"])
    long_ago = 1_700_000_000
    _db.record_claude_session(
        db_path, started_at=long_ago - 60, finished_at=long_ago,
        duration_ms=60000, num_turns=1, input_tokens=10, output_tokens=5,
        total_cost_usd=0.01, model="sonnet", is_error=False,
    )
    # после сессии тимлид написал в чат
    _db.post_chat_message(db_path, "тимлид", "готово")
    r = client.get("/api/team/silence")
    j = r.get_json()
    assert j["silent"] is False
    assert "отчитался" in j["reason"]


# === /api/router/pick ===


def test_api_router_pick_empty(client) -> None:
    r = client.get("/api/router/pick")
    assert r.status_code == 200
    j = r.get_json()
    assert j["model_alias"] == "haiku"
    assert j["counters"]["total_workable"] == 0


def test_api_router_pick_with_archi_task(client) -> None:
    client.post("/api/tasks", json={"title": "Спроектируй модуль X", "labels": ["design"]})
    r = client.get("/api/router/pick")
    j = r.get_json()
    assert j["model_alias"] == "opus"


# === /api/chat ===


def test_api_chat_empty(client) -> None:
    r = client.get("/api/chat")
    assert r.status_code == 200
    assert r.get_json()["messages"] == []


def test_api_chat_post_and_list(client) -> None:
    r = client.post("/api/chat", json={"author": "дмитрий", "text": "привет"})
    assert r.status_code == 201

    r = client.get("/api/chat")
    msgs = r.get_json()["messages"]
    assert len(msgs) == 1
    assert msgs[0]["author"] == "дмитрий"
    assert msgs[0]["text"] == "привет"


def test_api_chat_post_empty_text_returns_400(client) -> None:
    r = client.post("/api/chat", json={"author": "дмитрий", "text": "   "})
    assert r.status_code == 400


def test_api_chat_get_since(client) -> None:
    """Параметр since фильтрует старые сообщения."""
    client.post("/api/chat", json={"author": "qa", "text": "1"})
    # since в далёком будущем — пусто
    r = client.get("/api/chat?since=9999999999")
    assert r.get_json()["messages"] == []


# === /api/inbox ===


def test_api_inbox_empty(client) -> None:
    r = client.get("/api/inbox")
    j = r.get_json()
    assert j["approvals"] == []
    assert j["reviews"] == []
    assert j["questions"] == []
    assert j["total"] == 0


def test_api_inbox_approvals(client) -> None:
    # Создаём задачу со status=needs_approval
    tid = client.post("/api/tasks", json={
        "title": "git push",
        "requires_approval": True,
        "status": "needs_approval",
    }).get_json()["задача"]["id"]
    r = client.get("/api/inbox")
    j = r.get_json()
    assert len(j["approvals"]) == 1
    assert j["approvals"][0]["id"] == tid
    assert j["total"] == 1


def test_api_inbox_reviews(client) -> None:
    tid = client.post("/api/tasks", json={"title": "x"}).get_json()["задача"]["id"]
    client.patch(f"/api/tasks/{tid}", json={"status": "review"})
    r = client.get("/api/inbox")
    j = r.get_json()
    assert len(j["reviews"]) == 1
    assert j["reviews"][0]["id"] == tid


def test_api_inbox_questions(client) -> None:
    """Задача назначена дмитрию (todo) — попадает в questions."""
    tid = client.post("/api/tasks", json={
        "title": "вопрос",
        "assignee": "дмитрий",
        "status": "todo",
    }).get_json()["задача"]["id"]
    r = client.get("/api/inbox")
    j = r.get_json()
    assert len(j["questions"]) == 1
    assert j["questions"][0]["id"] == tid


def test_api_inbox_approval_priority_over_questions(client) -> None:
    """Approval-задача дмитрию НЕ дублируется в questions."""
    client.post("/api/tasks", json={
        "title": "approve me",
        "assignee": "дмитрий",
        "status": "needs_approval",
        "requires_approval": True,
    })
    r = client.get("/api/inbox")
    j = r.get_json()
    assert len(j["approvals"]) == 1
    assert len(j["questions"]) == 0
    assert j["total"] == 1


def test_api_inbox_excludes_done_and_blocked(client) -> None:
    tid = client.post("/api/tasks", json={
        "title": "x",
        "assignee": "дмитрий",
        "status": "todo",
    }).get_json()["задача"]["id"]
    client.patch(f"/api/tasks/{tid}", json={"status": "done"})
    r = client.get("/api/inbox")
    j = r.get_json()
    assert j["total"] == 0


# === /api/usage ===


def test_api_usage_empty(client) -> None:
    r = client.get("/api/usage")
    assert r.status_code == 200
    j = r.get_json()
    # usage_summary возвращает dict — структура зависит от реализации
    assert isinstance(j, dict)


# === Comment mirroring to chat (Дмитрий) ===


def test_dmitry_comment_mirrored_to_chat(client) -> None:
    """Коммент Дмитрия должен зеркалиться в чат."""
    tid = client.post("/api/tasks", json={"title": "t"}).get_json()["задача"]["id"]
    client.post(f"/api/tasks/{tid}/comment", json={
        "author": "дмитрий",
        "text": "проверь",
    })
    msgs = client.get("/api/chat").get_json()["messages"]
    assert any("проверь" in m["text"] for m in msgs)


def test_system_approve_marker_not_mirrored(client) -> None:
    """approved at ... — системный маркер, не должен лететь в чат."""
    tid = client.post("/api/tasks", json={"title": "t"}).get_json()["задача"]["id"]
    client.post(f"/api/tasks/{tid}/comment", json={
        "author": "дмитрий",
        "text": "approved at 2026-05-21 10:00:00",
    })
    msgs = client.get("/api/chat").get_json()["messages"]
    assert msgs == []


def test_non_dmitry_comment_not_mirrored(client) -> None:
    """Коммент не от Дмитрия не зеркалится в чат."""
    tid = client.post("/api/tasks", json={"title": "t"}).get_json()["задача"]["id"]
    client.post(f"/api/tasks/{tid}/comment", json={
        "author": "тимлид",
        "text": "ок",
    })
    msgs = client.get("/api/chat").get_json()["messages"]
    assert msgs == []

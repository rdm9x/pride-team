"""Error-ветки и валидация в pride_tasks.tools.

Дополняет test_tools.py — там в основном happy-path. Здесь:
  - валидация пустых аргументов
  - notify_dmitry без конфига Telegram / с ошибкой отправки
  - chat_post валидация
  - add_dependency / get_dependencies error-ветки
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pride_tasks import alerts, tools


# === add_dependency ===


def test_add_dependency_empty_task_id(db_path: Path) -> None:
    res = tools.add_dependency("", "abc", db_path=db_path)
    assert res["статус"] == "error"
    assert "обязательны" in res["причина"]


def test_add_dependency_empty_depends_on(db_path: Path) -> None:
    res = tools.add_dependency("abc", "", db_path=db_path)
    assert res["статус"] == "error"


def test_add_dependency_unknown_task(db_path: Path) -> None:
    res = tools.add_dependency("aaaaaa", "bbbbbb", db_path=db_path)
    assert res["статус"] == "error"
    assert "причина" in res


# === remove_dependency ===


def test_remove_dependency_unknown(db_path: Path) -> None:
    res = tools.remove_dependency("nope", "alsono", db_path=db_path)
    assert res["статус"] == "not_found"


# === get_dependencies ===


def test_get_dependencies_empty_task_id(db_path: Path) -> None:
    res = tools.get_dependencies("", db_path=db_path)
    assert res["статус"] == "error"
    assert "пустой" in res["причина"]


def test_get_dependencies_for_existing_task(db_path: Path) -> None:
    from pride_tasks import db
    t = db.insert_task(db_path, title="a")
    res = tools.get_dependencies(t["id"], db_path=db_path)
    assert res["статус"] == "ok"
    assert res["blocked_by"] == []
    assert res["blocking"] == []


# === notify_dmitry ===


def test_notify_dmitry_no_env(monkeypatch, db_path: Path) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    res = tools.notify_dmitry("привет", db_path=db_path)
    assert res["статус"] == "skip"
    assert "TELEGRAM" in res["причина"]


def test_notify_dmitry_empty_text(monkeypatch, db_path: Path) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    res = tools.notify_dmitry("   ", db_path=db_path)
    assert res["статус"] == "error"
    assert "пустой" in res["причина"]


def test_notify_dmitry_send_failure(monkeypatch, db_path: Path) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")

    fake = MagicMock()
    fake.send.side_effect = alerts.TelegramAlertError("network down")
    with patch.object(alerts, "from_env", return_value=fake):
        res = tools.notify_dmitry("важно", db_path=db_path)
    assert res["статус"] == "error"
    assert "network" in res["причина"]


def test_notify_dmitry_happy(monkeypatch, db_path: Path) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")

    fake = MagicMock()
    with patch.object(alerts, "from_env", return_value=fake):
        res = tools.notify_dmitry("важно", level="warn", db_path=db_path)
    assert res["статус"] == "ok"
    fake.send.assert_called_once()
    # level прокинулся
    assert fake.send.call_args.kwargs["level"] == "warn"


# === chat_post ===


def test_chat_post_empty_author(db_path: Path) -> None:
    res = tools.chat_post("", "hi", db_path=db_path)
    assert res["статус"] == "error"


def test_chat_post_empty_text(db_path: Path) -> None:
    res = tools.chat_post("дмитрий", "   ", db_path=db_path)
    assert res["статус"] == "error"


def test_chat_post_happy(db_path: Path) -> None:
    res = tools.chat_post("дмитрий", "привет", db_path=db_path)
    assert res["статус"] == "ok"
    assert res["сообщение"]["author"] == "дмитрий"


# === chat_recent ===


def test_chat_recent_empty(db_path: Path) -> None:
    res = tools.chat_recent(db_path=db_path)
    assert res["статус"] == "ok"
    assert res["всего"] == 0
    assert res["сообщения"] == []


def test_chat_recent_returns_messages(db_path: Path) -> None:
    tools.chat_post("дмитрий", "a", db_path=db_path)
    tools.chat_post("тимлид", "b", db_path=db_path)
    res = tools.chat_recent(db_path=db_path)
    assert res["всего"] == 2

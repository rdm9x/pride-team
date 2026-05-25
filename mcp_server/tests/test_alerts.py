"""Тесты Telegram-алертера (devboard_tasks.alerts).

Покрываются:
  - конструктор TelegramAlerter (валидация bot_token / chat_id)
  - .url
  - .send() — happy-path, http-ошибки, network-ошибки, ok=false, bad json
  - все уровни (info/warn/error/ok) — корректные emoji-префиксы
  - from_env() — все ветки (нет токена, нет чата, числовой chat, строковый chat)
  - load_env_file() — отсутствующий файл, комментарии, кавычки, не-перезаписывает
"""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from devboard_tasks import alerts


# === TelegramAlerter constructor ===


def test_constructor_rejects_empty_token() -> None:
    with pytest.raises(ValueError, match="bot_token"):
        alerts.TelegramAlerter(bot_token="", chat_id=123)


def test_constructor_rejects_none_chat_id() -> None:
    with pytest.raises(ValueError, match="chat_id"):
        alerts.TelegramAlerter(bot_token="token", chat_id=None)  # type: ignore[arg-type]


def test_constructor_rejects_empty_chat_id() -> None:
    with pytest.raises(ValueError, match="chat_id"):
        alerts.TelegramAlerter(bot_token="token", chat_id="")


def test_constructor_accepts_numeric_chat_id() -> None:
    a = alerts.TelegramAlerter(bot_token="t123", chat_id=456789)
    assert a.url == "https://api.telegram.org/bott123/sendMessage"


def test_constructor_accepts_string_chat_id() -> None:
    a = alerts.TelegramAlerter(bot_token="t", chat_id="@channel")
    assert "@channel" not in a.url  # chat_id уходит в payload, не в URL


# === send() ===


def _make_response(status: int = 200, body: dict | str | None = None):
    """Хелпер: подделка ответа urlopen() (контекстный менеджер)."""
    body = body if body is not None else {"ok": True}
    raw = json.dumps(body).encode("utf-8") if isinstance(body, dict) else body.encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.read.return_value = raw
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = False
    return mock_resp


def test_send_happy_path() -> None:
    a = alerts.TelegramAlerter(bot_token="t", chat_id=1)
    with patch("urllib.request.urlopen", return_value=_make_response()) as m:
        a.send("привет")
    assert m.called
    # Проверим что в payload попал префикс info по умолчанию
    req = m.call_args[0][0]
    payload = json.loads(req.data.decode("utf-8"))
    assert payload["chat_id"] == 1
    assert payload["text"].startswith("ℹ️")
    assert "привет" in payload["text"]


@pytest.mark.parametrize("level,prefix", [
    ("info", "ℹ️"),
    ("warn", "⚠️"),
    ("error", "🚨"),
    ("ok", "✅"),
])
def test_send_level_prefix(level: str, prefix: str) -> None:
    a = alerts.TelegramAlerter(bot_token="t", chat_id=1)
    with patch("urllib.request.urlopen", return_value=_make_response()) as m:
        a.send("тест", level=level)
    payload = json.loads(m.call_args[0][0].data.decode("utf-8"))
    assert payload["text"].startswith(prefix)


def test_send_unknown_level_falls_back_to_info() -> None:
    a = alerts.TelegramAlerter(bot_token="t", chat_id=1)
    with patch("urllib.request.urlopen", return_value=_make_response()) as m:
        a.send("тест", level="unknown")
    payload = json.loads(m.call_args[0][0].data.decode("utf-8"))
    assert payload["text"].startswith("ℹ️")


def test_send_raises_on_non_200_status() -> None:
    a = alerts.TelegramAlerter(bot_token="t", chat_id=1)
    resp = _make_response(status=500, body={"ok": False})
    with patch("urllib.request.urlopen", return_value=resp):
        with pytest.raises(alerts.TelegramAlertError, match="http 500"):
            a.send("тест")


def test_send_raises_on_ok_false() -> None:
    a = alerts.TelegramAlerter(bot_token="t", chat_id=1)
    resp = _make_response(status=200, body={"ok": False, "description": "boom"})
    with patch("urllib.request.urlopen", return_value=resp):
        with pytest.raises(alerts.TelegramAlertError, match="ok=false"):
            a.send("тест")


def test_send_raises_on_bad_json() -> None:
    a = alerts.TelegramAlerter(bot_token="t", chat_id=1)
    resp = _make_response(status=200, body="not-json")
    with patch("urllib.request.urlopen", return_value=resp):
        with pytest.raises(alerts.TelegramAlertError, match="bad json"):
            a.send("тест")


def test_send_handles_http_error() -> None:
    a = alerts.TelegramAlerter(bot_token="t", chat_id=1)
    err = urllib.error.HTTPError(
        url="x", code=429, msg="Too Many Requests",
        hdrs=None, fp=io.BytesIO(b"slow down"),
    )
    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(alerts.TelegramAlertError, match="http 429"):
            a.send("тест")


def test_send_handles_url_error() -> None:
    a = alerts.TelegramAlerter(bot_token="t", chat_id=1)
    err = urllib.error.URLError("connection refused")
    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(alerts.TelegramAlertError, match="network"):
            a.send("тест")


# === from_env() ===


def test_from_env_no_token_returns_none(monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    assert alerts.from_env() is None


def test_from_env_no_chat_returns_none(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert alerts.from_env() is None


def test_from_env_empty_token_returns_none(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "   ")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    assert alerts.from_env() is None


def test_from_env_numeric_chat_id(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654")
    a = alerts.from_env()
    assert a is not None
    assert a._chat_id == 987654  # int


def test_from_env_string_chat_id(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "@channel")
    a = alerts.from_env()
    assert a is not None
    assert a._chat_id == "@channel"


# === load_env_file() ===


def test_load_env_file_missing(tmp_path: Path) -> None:
    n = alerts.load_env_file(tmp_path / "no-such.env")
    assert n == 0


def test_load_env_file_parses_keys(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("TEST_KEY_A", raising=False)
    monkeypatch.delenv("TEST_KEY_B", raising=False)
    env = tmp_path / ".env"
    env.write_text(
        "# комментарий\n"
        "TEST_KEY_A=valueA\n"
        '\n'
        'TEST_KEY_B="value with spaces"\n',
        encoding="utf-8",
    )
    n = alerts.load_env_file(env)
    import os
    assert n == 2
    assert os.environ["TEST_KEY_A"] == "valueA"
    assert os.environ["TEST_KEY_B"] == "value with spaces"


def test_load_env_file_does_not_overwrite(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALREADY_SET", "original")
    env = tmp_path / ".env"
    env.write_text("ALREADY_SET=new\n", encoding="utf-8")
    n = alerts.load_env_file(env)
    import os
    assert n == 0  # ничего не загружено — переменная уже была
    assert os.environ["ALREADY_SET"] == "original"


def test_load_env_file_ignores_malformed_lines(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("GOOD_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text(
        "не строка с равно\n"
        "GOOD_KEY=ok\n"
        "  \n",
        encoding="utf-8",
    )
    n = alerts.load_env_file(env)
    import os
    assert n == 1
    assert os.environ["GOOD_KEY"] == "ok"


def test_load_env_file_strips_single_quotes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("QUOTED", raising=False)
    env = tmp_path / ".env"
    env.write_text("QUOTED='in-quotes'\n", encoding="utf-8")
    alerts.load_env_file(env)
    import os
    assert os.environ["QUOTED"] == "in-quotes"

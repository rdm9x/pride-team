"""Telegram-алерты для малой команды devboard.

Минимальная обёртка над Telegram Bot HTTP API (sendMessage) на стандартной
библиотеке. Используется:
  - тимлидом через MCP-tool `notify_user`,
  - дашбордом для алертов (опционально — задача висит >2ч, лимит подписки
    близок и т.п. — настраивается отдельно).

Конфиг через env:
  TELEGRAM_BOT_TOKEN — токен бота (выдаёт @BotFather).
  TELEGRAM_CHAT_ID   — числовой id чата (или @username канала).

Если переменных нет — `from_env()` возвращает None, отправка пропускается.
Алерты НИКОГДА не должны ронять основной процесс.

Перенесено из pride_dev/alerts/telegram.py (часть pride-dev-department,
закрыта в пользу фокуса на devboard). httpx убран — для одного POST'а
достаточно urllib.request.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Union

__all__ = ["TelegramAlertError", "TelegramAlerter", "from_env", "load_env_file"]

_LOG = logging.getLogger(__name__)

_LEVEL_PREFIX = {
    "info": "ℹ️",
    "warn": "⚠️",
    "error": "🚨",
    "ok": "✅",
}


class TelegramAlertError(Exception):
    """Ошибка отправки в Telegram."""


class TelegramAlerter:
    """Лёгкий sync-клиент к Telegram Bot API.

    Использует urllib.request — без зависимостей. Подходит для редких алертов
    (десятки в день, не тысячи).
    """

    API_BASE = "https://api.telegram.org"

    def __init__(
        self,
        bot_token: str,
        chat_id: Union[int, str],
        *,
        timeout: float = 5.0,
    ) -> None:
        if not bot_token:
            raise ValueError("bot_token обязателен")
        if chat_id == "" or chat_id is None:
            raise ValueError("chat_id обязателен")
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._timeout = timeout

    @property
    def url(self) -> str:
        return f"{self.API_BASE}/bot{self._bot_token}/sendMessage"

    def send(self, message: str, *, level: str = "info") -> None:
        """Отправить алерт. На любую ошибку — TelegramAlertError."""
        prefix = _LEVEL_PREFIX.get(level, _LEVEL_PREFIX["info"])
        text = f"{prefix} {message}"
        payload = json.dumps({"chat_id": self._chat_id, "text": text}).encode("utf-8")
        req = urllib.request.Request(
            self.url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                body = resp.read().decode("utf-8", "replace")
                if resp.status != 200:
                    raise TelegramAlertError(f"http {resp.status}: {body[:512]}")
                try:
                    data = json.loads(body)
                except ValueError as exc:
                    raise TelegramAlertError(f"bad json: {body[:512]}") from exc
                if not data.get("ok"):
                    raise TelegramAlertError(f"telegram ok=false: {body[:512]}")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace") if exc.fp else ""
            _LOG.warning("telegram: HTTP %s — %s", exc.code, body[:200])
            raise TelegramAlertError(f"http {exc.code}: {body[:512]}") from exc
        except urllib.error.URLError as exc:
            _LOG.warning("telegram: сетевая ошибка — %s", exc)
            raise TelegramAlertError(f"network: {exc}") from exc


def from_env() -> Optional[TelegramAlerter]:
    """Собрать TelegramAlerter из env-переменных. None если конфига нет."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        return None
    chat_value: Union[int, str]
    try:
        chat_value = int(chat)
    except ValueError:
        chat_value = chat
    return TelegramAlerter(bot_token=token, chat_id=chat_value)


def load_env_file(path: Path) -> int:
    """Простой .env-загрузчик (KEY=VALUE строки, # комментарии).

    Не перезаписывает уже установленные переменные. Возвращает количество
    загруженных ключей.
    """
    if not path.exists():
        return 0
    loaded = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded += 1
    return loaded

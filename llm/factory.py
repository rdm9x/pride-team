"""Factory `create_provider(config) -> LLMProvider` (ADR-001 §2.5, §6.2).

Маппит фрагмент frontmatter роли на конкретный провайдер. По мере
реализации провайдеров (E6.3 — claude CLI, E6.4 — OpenAI, E6.5 — Ollama)
ветки превращаются из `NotImplementedError` в реальный билдер.

Auto-detect по env (см. ADR-001 §6.2): если `llm` во frontmatter не
указан, выбирается первая доступная опция в порядке
ANTHROPIC_API_KEY → OPENAI_API_KEY → ollama (по env-URL). Полноценный
ping Ollama здесь не делается — это часть E6.6 (frontmatter-парсер
ролей). На этапе E6.2 auto-detect ограничен env-переменными.
"""

from __future__ import annotations

import os
from typing import Any

from .base import LLMConfigError, LLMProvider
from .mock import MockProvider


_KNOWN_PROVIDERS = {"claude", "openai", "ollama", "mock"}


def create_provider(config: dict[str, Any]) -> LLMProvider:
    """Собрать `LLMProvider` по `config` — фрагменту frontmatter роли.

    Поддерживаемые ключи:
        llm: одно из `claude`, `openai`, `ollama`, `mock`. Если отсутствует
            или равно `auto`/`None` — выбирается auto-detect по env.
        model: имя модели (например `claude-opus-4-7`, `gpt-4o`,
            `llama3.1`). Конкретный провайдер сам подставляет дефолт,
            если опущен.
        api_key_env: имя env-переменной с API-ключом (для cloud-
            провайдеров). Опционально.
        extras: dict с провайдер-специфичными настройками
            (`temperature`, `max_tokens`, CLI-флаги для claude и т.п.).

    Спец-значение `llm: mock` существует для тестов и принимает
    дополнительные ключи как kwargs `MockProvider` (`text`, `stop_reason`,
    `model`, …).

    Raises:
        LLMConfigError: неизвестный `llm`, либо при auto-detect ни один
            провайдер не доступен.
        NotImplementedError: `llm` известен, но провайдер ещё не
            реализован в текущей версии (E6.3-E6.5).
    """

    if not isinstance(config, dict):
        raise LLMConfigError(
            f"create_provider: ожидаю dict, получил {type(config).__name__}"
        )

    raw_llm = config.get("llm")
    llm = _normalize_llm(raw_llm)

    if llm is None:
        llm = _autodetect()

    if llm not in _KNOWN_PROVIDERS:
        raise LLMConfigError(
            f"create_provider: неизвестный llm={llm!r}. "
            f"Допустимые: {sorted(_KNOWN_PROVIDERS)}."
        )

    if llm == "mock":
        return _build_mock(config)

    if llm == "claude":
        return _build_claude(config)

    if llm == "openai":
        return _build_openai(config)

    if llm == "ollama":
        return _build_ollama(config)

    # Сюда не должны добраться — выше уже проверили _KNOWN_PROVIDERS.
    raise LLMConfigError(f"create_provider: внутренняя ошибка, llm={llm!r}")


def _normalize_llm(raw: Any) -> str | None:
    """Привести `llm` к строке либо None (для auto-detect)."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise LLMConfigError(
            f"create_provider: поле 'llm' должно быть строкой, "
            f"получил {type(raw).__name__}"
        )
    norm = raw.strip().lower()
    if norm in ("", "auto"):
        return None
    return norm


def _autodetect() -> str:
    """Выбор провайдера по доступности credentials (ADR-001 §6.2).

    Порядок: ANTHROPIC_API_KEY → OPENAI_API_KEY → ollama (по env-URL).
    На этапе E6.2 ping Ollama не делается: достаточно, чтобы был задан
    `OLLAMA_URL`. Полноценный TCP-ping — часть E6.6.
    """
    if os.getenv("ANTHROPIC_API_KEY"):
        return "claude"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    if os.getenv("OLLAMA_URL"):
        return "ollama"
    raise LLMConfigError(
        "No LLM provider available. Set ANTHROPIC_API_KEY / "
        "OPENAI_API_KEY or run `ollama serve` (с OLLAMA_URL)."
    )


def _build_mock(config: dict[str, Any]) -> MockProvider:
    """Собрать `MockProvider`, пробросив тестовые поля как kwargs."""
    allowed = {"text", "content", "chunks", "stop_reason", "model", "usage"}
    kwargs = {k: v for k, v in config.items() if k in allowed}
    return MockProvider(**kwargs)


def _build_claude(config: dict[str, Any]) -> LLMProvider:
    """Собрать `ClaudeCLIProvider` по `config` (ADR-001 §6.2, E6.3).

    Распознаваемые ключи (поверх общих `llm`/`model`):
        allowed_tools: list[str] — `--allowed-tools` для CLI.
        mcp_config: str — путь к `.mcp.json`.
        permission_mode: str — `bypassPermissions` / `default` / ...
        cli_path: str — путь к бинарю `claude` (по умолчанию — PATH).
        extras.extra_args: list[str] — произвольные доп. CLI-флаги.

    Импорт ClaudeCLIProvider — lazy, чтобы factory не тащил его при
    сборке другого провайдера (симметрично OpenAI).
    """
    from .claude_cli_provider import ClaudeCLIProvider

    extras = config.get("extras") or {}
    kwargs: dict[str, Any] = {}
    if model := config.get("model"):
        kwargs["model"] = model
    if (allowed := config.get("allowed_tools")) is not None:
        kwargs["allowed_tools"] = allowed
    if mcp_config := config.get("mcp_config"):
        kwargs["mcp_config"] = mcp_config
    if permission_mode := config.get("permission_mode"):
        kwargs["permission_mode"] = permission_mode
    if cli_path := config.get("cli_path"):
        kwargs["cli_path"] = cli_path
    if extra_args := extras.get("extra_args"):
        kwargs["extra_args"] = list(extra_args)
    return ClaudeCLIProvider(**kwargs)


def _build_openai(config: dict[str, Any]) -> LLMProvider:
    """Собрать `OpenAIProvider` по `config`.

    Поддерживает `api_key_env` (имя переменной окружения с ключом;
    по умолчанию — `OPENAI_API_KEY`). Если переменная пуста, провайдер
    сам бросит `LLMConfigError`.
    """
    # Импорт здесь — чтобы factory не тащил openai-зависимость
    # при сборке Mock/Claude/Ollama (lazy, ADR-001 §6.2).
    from .openai_provider import OpenAIProvider

    model = config.get("model")
    if not model:
        raise LLMConfigError(
            "create_provider(openai): поле 'model' обязательно "
            "(например, 'gpt-4o' или 'gpt-4o-mini')."
        )
    api_key_env = config.get("api_key_env", "OPENAI_API_KEY")
    api_key = os.environ.get(api_key_env)
    base_url = (config.get("extras") or {}).get("base_url")
    return OpenAIProvider(model=model, api_key=api_key, base_url=base_url)


def _build_ollama(config: dict[str, Any]) -> LLMProvider:
    """Собрать `OllamaProvider` по `config` (ADR-001 §6.2, E6.5).

    Поддерживаемые ключи (поверх общих `llm`/`model`):
        model: имя модели в Ollama (например `llama3.1`, `mistral`).
            По умолчанию — `llama3.1`.
        extras.base_url: URL Ollama-сервера (по умолчанию
            `http://localhost:11434`, или `OLLAMA_URL` из env).
        extras.timeout: таймаут HTTP-запроса в секундах.

    Импорт OllamaProvider — lazy, чтобы factory не тащил httpx-зависимость
    при сборке Mock/Claude/OpenAI.
    """
    from .ollama_provider import OllamaProvider

    extras = config.get("extras") or {}
    model = config.get("model") or "llama3.1"
    base_url = (
        extras.get("base_url")
        or os.environ.get("OLLAMA_URL")
        or "http://localhost:11434"
    )
    kwargs: dict[str, Any] = {"model": model, "base_url": base_url}
    if timeout := extras.get("timeout"):
        kwargs["timeout"] = float(timeout)
    return OllamaProvider(**kwargs)


__all__ = ["create_provider"]

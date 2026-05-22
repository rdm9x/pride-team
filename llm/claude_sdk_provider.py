"""`ClaudeSDKProvider` — заглушка (бонус к E6.3).

Этот файл — каркас под будущую реализацию `LLMProvider` через
официальный `anthropic` Python SDK (без зависимости от Claude Code CLI).
Сама E6.3 покрывается `ClaudeCLIProvider`; SDK-вариант оставлен на
потом — отдельной задачей.

Не подключён в `llm.factory.create_provider`. Импорт самого класса не
триггерит `import anthropic` — это происходит только при инстансах.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

from .base import (
    LLMChunk,
    LLMConfigError,
    LLMProvider,
    LLMResponse,
    Message,
    Tool,
)


@dataclass
class ClaudeSDKProvider(LLMProvider):
    """Stub: реализация через `anthropic` Python SDK будет добавлена позже.

    Пока конструктор валидирует параметры, но `invoke` / `stream` бросают
    `NotImplementedError`. Когда дойдут руки — поменяем тело методов и
    зарегистрируем в factory через дополнительный `llm: "claude-sdk"`.
    """

    model: str = "claude-opus-4-7"
    api_key: Optional[str] = None
    api_key_env: str = "ANTHROPIC_API_KEY"
    max_tokens: int = 4096
    extras: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.model, str) or not self.model.strip():
            raise LLMConfigError(
                "ClaudeSDKProvider: 'model' должен быть непустой строкой."
            )
        self.model = self.model.strip()

    async def invoke(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        system_prompt: str | None = None,
    ) -> LLMResponse:
        raise NotImplementedError(
            "ClaudeSDKProvider пока не реализован — используйте "
            "ClaudeCLIProvider (E6.3) или MockProvider для тестов."
        )

    async def stream(  # type: ignore[override]
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        system_prompt: str | None = None,
    ) -> AsyncIterator[LLMChunk]:
        raise NotImplementedError(
            "ClaudeSDKProvider.stream пока не реализован — используйте "
            "ClaudeCLIProvider (E6.3)."
        )
        # Сделать функцию async-generator'ом — недостижимо, но успокаивает
        # type-checker'ов, ожидающих AsyncIterator.
        if False:  # pragma: no cover
            yield  # type: ignore[unreachable]


__all__ = ["ClaudeSDKProvider"]

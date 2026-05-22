"""`MockProvider` — детерминированный LLM-провайдер для unit-тестов.

Не делает сетевых вызовов, не зависит от внешних SDK. Возвращает
заранее заданные ответы / стрим-чанки, что позволяет тестировать
агент-loop, MCP-bridge, дашборд-SSE без поднятия реального LLM.

Использование:

    >>> provider = MockProvider(text="привет")
    >>> response = await provider.invoke(messages=[Message("user", "hi")])
    >>> response.content[0].text
    'привет'

Можно подсунуть и tool_use:

    >>> provider = MockProvider(content=[ToolUseBlock(id="toolu_1",
    ...                                                name="ping",
    ...                                                input={})],
    ...                          stop_reason="tool_use")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator, Iterable

from .base import (
    ContentBlock,
    LLMChunk,
    LLMProvider,
    LLMResponse,
    Message,
    MessageStop,
    StopReason,
    TextBlock,
    TextDelta,
    Tool,
    ToolUseBlock,
    ToolUseDelta,
    ToolUseEnd,
    ToolUseStart,
    Usage,
)


@dataclass
class MockProvider(LLMProvider):
    """Минимальный провайдер для тестов.

    Параметры:
        text: если задан и `content` пуст — будет возвращён один
            `TextBlock(text=text)`.
        content: явный список блоков ответа. Перекрывает `text`.
        chunks: явный список стрим-чанков для `stream()`. Если не задан,
            генерируется автоматически: один `TextDelta` на слово из
            `text` + финальный `MessageStop`.
        stop_reason: причина остановки, попадает в `LLMResponse` и в
            финальный `MessageStop`.
        model: имя модели для отчётности.
        usage: счётчик токенов (по умолчанию все нули).
        calls: журнал вызовов — каждый элемент это dict
            `{"method": "invoke"|"stream", "messages": [...],
              "tools": [...], "system_prompt": "..."}`. Полезно в
            assert'ах теста.
    """

    text: str = "ok"
    content: list[ContentBlock] = field(default_factory=list)
    chunks: list[LLMChunk] | None = None
    stop_reason: StopReason = "end_turn"
    model: str = "mock-1"
    usage: Usage = field(default_factory=Usage)
    calls: list[dict] = field(default_factory=list)

    def _resolve_content(self) -> list[ContentBlock]:
        if self.content:
            return list(self.content)
        return [TextBlock(text=self.text)]

    def _record(
        self,
        method: str,
        messages: list[Message],
        tools: list[Tool] | None,
        system_prompt: str | None,
    ) -> None:
        self.calls.append(
            {
                "method": method,
                "messages": list(messages),
                "tools": list(tools) if tools else None,
                "system_prompt": system_prompt,
            }
        )

    async def invoke(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        system_prompt: str | None = None,
    ) -> LLMResponse:
        self._record("invoke", messages, tools, system_prompt)
        return LLMResponse(
            content=self._resolve_content(),
            stop_reason=self.stop_reason,
            usage=self.usage,
            model=self.model,
            raw=None,
        )

    async def stream(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        system_prompt: str | None = None,
    ) -> AsyncIterator[LLMChunk]:
        self._record("stream", messages, tools, system_prompt)

        chunks: Iterable[LLMChunk]
        if self.chunks is not None:
            chunks = self.chunks
        else:
            chunks = self._auto_chunks()

        for chunk in chunks:
            yield chunk

    def _auto_chunks(self) -> list[LLMChunk]:
        """Авто-стрим: TextDelta'ы для текста + tool_use_* для tool-блоков."""

        out: list[LLMChunk] = []
        for block in self._resolve_content():
            if isinstance(block, TextBlock):
                # По слову — чтобы тесты могли проверить накопление.
                parts = block.text.split(" ")
                for i, p in enumerate(parts):
                    suffix = "" if i == len(parts) - 1 else " "
                    out.append(TextDelta(text=p + suffix))
            elif isinstance(block, ToolUseBlock):
                out.append(ToolUseStart(id=block.id, name=block.name))
                # одним куском, чтобы не тащить json.dumps в моки.
                out.append(
                    ToolUseDelta(id=block.id, partial_json=repr(block.input))
                )
                out.append(ToolUseEnd(id=block.id, input=block.input))
            # ToolResultBlock в ответе модели не появляется — пропускаем.
        out.append(
            MessageStop(
                stop_reason=self.stop_reason,
                usage=self.usage,
                model=self.model,
            )
        )
        return out


__all__ = ["MockProvider"]

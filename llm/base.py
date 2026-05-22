"""Базовый контракт `LLMProvider` (ADR-001).

Этот модуль определяет провайдер-агностичный интерфейс к LLM и набор
dataclasses, описывающих сообщения, инструменты, ответы и стрим-чанки.
Формат — Anthropic-style (см. ADR-001 §2.2): `system` — отдельный
аргумент, content внутри сообщения — список блоков (текст / tool_use /
tool_result), что строго мощнее OpenAI-схемы и не теряет информации
при конвертации в обратную сторону.

Конкретные реализации провайдеров (`ClaudeCLIProvider`,
`OpenAIProvider`, `OllamaProvider`) — отдельные задачи E6.3-E6.5.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator, Literal, Union


# ---------------------------------------------------------------------------
# Content blocks
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TextBlock:
    """Кусок обычного текста внутри сообщения."""

    text: str
    type: Literal["text"] = "text"


@dataclass(frozen=True)
class ToolUseBlock:
    """Запрос модели на вызов инструмента.

    `id` — идентификатор tool-use, который потом должен совпасть с
    `ToolResultBlock.tool_use_id`. У Anthropic выглядит как `toolu_*`;
    провайдеры OpenAI/Ollama нормализуют ID к Anthropic-формату (см.
    ADR-001 §3, риск «Tool-call ID-несовместимость»).
    """

    id: str
    name: str
    input: dict
    type: Literal["tool_use"] = "tool_use"


@dataclass(frozen=True)
class ToolResultBlock:
    """Результат вызова инструмента, возвращаемый в модель.

    В Anthropic-схеме tool_result-блок живёт внутри `user`-сообщения.
    `content` — либо строка, либо список TextBlock'ов.
    """

    tool_use_id: str
    content: Union[str, list["TextBlock"]]
    is_error: bool = False
    type: Literal["tool_result"] = "tool_result"


ContentBlock = Union[TextBlock, ToolUseBlock, ToolResultBlock]


# ---------------------------------------------------------------------------
# Messages, Tools
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Message:
    """Сообщение в диалоге.

    `role` — только `user`/`assistant`. `system` НЕ роль, а отдельный
    аргумент `system_prompt` в `LLMProvider.invoke/stream` (см. ADR-001).
    `content` — либо строка (тогда трактуется как один `TextBlock`),
    либо список `ContentBlock`'ов.
    """

    role: Literal["user", "assistant"]
    content: Union[str, list[ContentBlock]]


@dataclass(frozen=True)
class Tool:
    """Описание инструмента, доступного модели.

    `input_schema` — JSON Schema (draft 2020-12). Anthropic принимает
    как есть; OpenAI оборачивает в `{"type": "function", "function": ...}`
    на стороне `OpenAIProvider`; Ollama сериализует в системный промт
    с JSON-протоколом (см. ADR-001 §2.3, §6.1).
    """

    name: str
    description: str
    input_schema: dict


# ---------------------------------------------------------------------------
# Usage, Response, Chunks
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Usage:
    """Счётчик токенов одного цикла запрос/ответ.

    `cache_creation_input_tokens` и `cache_read_input_tokens` есть у
    Anthropic и (с недавнего времени) у OpenAI. У Ollama всегда 0 —
    это документировано, не баг (см. ADR-001 §3, риск «Cache»).
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


StopReason = Literal["end_turn", "tool_use", "max_tokens", "stop_sequence"]


@dataclass(frozen=True)
class LLMResponse:
    """Финальный ответ одного цикла `invoke`.

    `content` может содержать `TextBlock` и `ToolUseBlock` вперемешку
    (Anthropic-стиль). Если есть tool_use — вызывающий (агент-loop)
    отвечает за их выполнение и подкладывание `ToolResultBlock`
    в следующее `user`-сообщение.
    """

    content: list[ContentBlock]
    stop_reason: StopReason
    usage: Usage
    model: str
    raw: Union[dict, None] = None


# --- Stream chunks ----------------------------------------------------------


@dataclass(frozen=True)
class TextDelta:
    """Инкрементальный кусочек обычного текста."""

    text: str
    type: Literal["text_delta"] = "text_delta"


@dataclass(frozen=True)
class ToolUseStart:
    """Начало tool_use-блока в стриме."""

    id: str
    name: str
    type: Literal["tool_use_start"] = "tool_use_start"


@dataclass(frozen=True)
class ToolUseDelta:
    """Инкрементальный JSON-кусок аргументов tool_use."""

    id: str
    partial_json: str
    type: Literal["tool_use_delta"] = "tool_use_delta"


@dataclass(frozen=True)
class ToolUseEnd:
    """Закрытие tool_use-блока: финальные собранные `input` и id."""

    id: str
    input: dict
    type: Literal["tool_use_end"] = "tool_use_end"


@dataclass(frozen=True)
class MessageStop:
    """Конец генерации: причина остановки + финальная usage-статистика."""

    stop_reason: StopReason
    usage: Usage
    model: str
    type: Literal["message_stop"] = "message_stop"


LLMChunk = Union[TextDelta, ToolUseStart, ToolUseDelta, ToolUseEnd, MessageStop]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class LLMError(Exception):
    """Базовая ошибка LLM-слоя."""


class LLMConfigError(LLMError):
    """Ошибка конфигурации провайдера (нет API-ключа, неизвестный llm и т.п.)."""


class LLMTransportError(LLMError):
    """Сбой транспорта/сети при общении с провайдером."""


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class LLMProvider(ABC):
    """Единый интерфейс к LLM.

    Реализации (отдельные задачи): `ClaudeCLIProvider` (E6.3),
    `OpenAIProvider` (E6.4), `OllamaProvider` (E6.5), `MockProvider`
    (этот модуль — для unit-тестов агент-loop'а).

    Провайдер НЕ выполняет инструменты. Если модель вернула
    `ToolUseBlock`, агент-loop вызывает инструмент сам и подкладывает
    `ToolResultBlock` в следующее `user`-сообщение. Это разделение
    ответственностей позволяет переиспользовать одного провайдера для
    нескольких ролей.
    """

    #: Имя модели, фактически отвечающей (заполняется реализацией).
    model: str = ""

    @abstractmethod
    async def invoke(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        system_prompt: str | None = None,
    ) -> LLMResponse:
        """Один цикл запрос/ответ. Возвращает финальный `LLMResponse`."""

    @abstractmethod
    def stream(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        system_prompt: str | None = None,
    ) -> AsyncIterator[LLMChunk]:
        """Стриминговый вариант.

        Возвращает async-итератор `LLMChunk`'ов. Реализуется как
        `async def stream(...) -> AsyncIterator[LLMChunk]` через
        `yield` — Python трактует такую функцию как async-generator,
        поэтому метод объявлен не-async (чтобы сигнатура и для
        генератора, и для функции, возвращающей итератор, была одна).
        """


__all__ = [
    # blocks
    "TextBlock",
    "ToolUseBlock",
    "ToolResultBlock",
    "ContentBlock",
    # message / tool
    "Message",
    "Tool",
    # response / chunks
    "Usage",
    "StopReason",
    "LLMResponse",
    "TextDelta",
    "ToolUseStart",
    "ToolUseDelta",
    "ToolUseEnd",
    "MessageStop",
    "LLMChunk",
    # errors
    "LLMError",
    "LLMConfigError",
    "LLMTransportError",
    # abc
    "LLMProvider",
]

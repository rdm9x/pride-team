"""Multi-LLM абстракция devboard (ADR-001).

Публичный API:

    from llm import (
        LLMProvider,         # abstract base
        create_provider,     # factory по frontmatter роли
        Message, Tool,
        LLMResponse, LLMChunk,
    )

Конкретные реализации (`ClaudeCLIProvider`, `OpenAIProvider`,
`OllamaProvider`) — отдельные задачи E6.3-E6.5; до их готовности
`create_provider` для них бросает `NotImplementedError`. Для unit-
тестов используйте `llm='mock'` (см. `llm.mock.MockProvider`).
"""

from __future__ import annotations

from .base import (
    ContentBlock,
    LLMChunk,
    LLMConfigError,
    LLMError,
    LLMProvider,
    LLMResponse,
    LLMTransportError,
    Message,
    MessageStop,
    StopReason,
    TextBlock,
    TextDelta,
    Tool,
    ToolResultBlock,
    ToolUseBlock,
    ToolUseDelta,
    ToolUseEnd,
    ToolUseStart,
    Usage,
)
from .claude_cli_provider import ClaudeCLIProvider
from .factory import create_provider
from .mock import MockProvider
from .ollama_provider import OllamaProvider
from .openai_provider import OpenAIProvider

__all__ = [
    # core
    "LLMProvider",
    "create_provider",
    "Message",
    "Tool",
    "LLMResponse",
    "LLMChunk",
    # blocks
    "TextBlock",
    "ToolUseBlock",
    "ToolResultBlock",
    "ContentBlock",
    # response details
    "Usage",
    "StopReason",
    # stream details
    "TextDelta",
    "ToolUseStart",
    "ToolUseDelta",
    "ToolUseEnd",
    "MessageStop",
    # errors
    "LLMError",
    "LLMConfigError",
    "LLMTransportError",
    # test helper
    "MockProvider",
    # concrete providers
    "ClaudeCLIProvider",
    "OllamaProvider",
    "OpenAIProvider",
]

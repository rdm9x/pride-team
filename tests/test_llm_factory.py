"""Тесты `llm.factory.create_provider` и `llm.mock.MockProvider`.

Покрывают acceptance из задачи E6.2:

* Импорт `from llm import create_provider` работает.
* Factory корректно собирает mock-провайдер и бросает осмысленные
  ошибки для нереализованных claude/openai/ollama и неизвестных
  значений `llm`.
* Auto-detect по env-переменным (ADR-001 §6.2) выбирает правильный
  провайдер в порядке anthropic → openai → ollama.
* `MockProvider.invoke` возвращает заданный текст / tool_use-блок.
* `MockProvider.stream` yield'ит ожидаемую последовательность чанков и
  всегда заканчивается `MessageStop`.
* Базовый класс `LLMProvider` — действительно abstract: его нельзя
  инстанцировать напрямую.

Запуск: `python -m pytest tests/test_llm_factory.py -v`
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

import pytest

# Acceptance из задачи: импорт через публичный API пакета.
from llm import (
    ClaudeCLIProvider,
    LLMChunk,
    LLMConfigError,
    LLMProvider,
    LLMResponse,
    Message,
    MessageStop,
    MockProvider,
    TextBlock,
    TextDelta,
    Tool,
    ToolUseBlock,
    ToolUseEnd,
    ToolUseStart,
    Usage,
    create_provider,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def run(coro):
    """Лёгкий шим: запустить корутину в чистом event-loop'е."""
    return asyncio.new_event_loop().run_until_complete(coro)


async def _drain(stream: AsyncIterator[LLMChunk]) -> list[LLMChunk]:
    out: list[LLMChunk] = []
    async for chunk in stream:
        out.append(chunk)
    return out


@pytest.fixture(autouse=True)
def _clear_llm_env(monkeypatch):
    """Каждый тест стартует с чистым env (никакого утёкшего ключа)."""
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OLLAMA_URL"):
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


def test_llm_provider_is_abstract():
    """LLMProvider — ABC, прямая инстанциация запрещена."""
    with pytest.raises(TypeError):
        LLMProvider()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# Factory: ошибки и mock
# ---------------------------------------------------------------------------


def test_create_provider_requires_dict():
    with pytest.raises(LLMConfigError):
        create_provider("claude")  # type: ignore[arg-type]


def test_create_provider_unknown_llm_raises():
    with pytest.raises(LLMConfigError):
        create_provider({"llm": "gemini"})


def test_create_provider_non_string_llm_raises():
    with pytest.raises(LLMConfigError):
        create_provider({"llm": 42})


def test_create_provider_mock_returns_mock_provider():
    p = create_provider({"llm": "mock", "text": "пр"})
    assert isinstance(p, MockProvider)
    assert p.text == "пр"


def test_create_provider_claude_builds_cli_provider():
    """E6.3: для llm='claude' factory собирает ClaudeCLIProvider."""
    p = create_provider({"llm": "claude"})
    assert isinstance(p, ClaudeCLIProvider)
    # Дефолтная модель из конструктора провайдера.
    assert p.model == "claude-opus-4-7"


def test_create_provider_claude_passes_model_and_extras():
    """Поля из config (model, allowed_tools, mcp_config) пробрасываются."""
    p = create_provider(
        {
            "llm": "claude",
            "model": "claude-haiku-4",
            "allowed_tools": ["Read", "Bash"],
            "mcp_config": "/tmp/.mcp.json",
            "permission_mode": "default",
            "extras": {"extra_args": ["--no-color"]},
        }
    )
    assert isinstance(p, ClaudeCLIProvider)
    assert p.model == "claude-haiku-4"
    assert p.allowed_tools == ["Read", "Bash"]
    assert p.mcp_config == "/tmp/.mcp.json"
    assert p.permission_mode == "default"
    assert p.extra_args == ["--no-color"]


def test_create_provider_openai_requires_model():
    """E6.4: openai-провайдер реализован, но без model factory падает."""
    with pytest.raises(LLMConfigError, match="model"):
        create_provider({"llm": "openai"})


def test_create_provider_openai_requires_api_key(monkeypatch):
    """E6.4: без OPENAI_API_KEY провайдер бросает LLMConfigError."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(LLMConfigError, match="OPENAI_API_KEY"):
        create_provider({"llm": "openai", "model": "gpt-4o"})


def test_create_provider_openai_builds_with_api_key(monkeypatch):
    """E6.4: при наличии env-ключа OpenAIProvider создаётся успешно."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    from llm import OpenAIProvider

    provider = create_provider({"llm": "openai", "model": "gpt-4o"})
    assert isinstance(provider, OpenAIProvider)
    assert provider.model == "gpt-4o"


def test_create_provider_ollama_not_implemented():
    with pytest.raises(NotImplementedError, match="E6.5"):
        create_provider({"llm": "ollama"})


def test_create_provider_normalizes_case_and_whitespace():
    """`  Claude ` → `claude` → ClaudeCLIProvider (без NotImplementedError)."""
    p = create_provider({"llm": "  Claude "})
    assert isinstance(p, ClaudeCLIProvider)


# ---------------------------------------------------------------------------
# Factory: auto-detect (ADR-001 §6.2)
# ---------------------------------------------------------------------------


def test_autodetect_anthropic_first(monkeypatch):
    """Anthropic должен победить openai/ollama. После E6.3 provider
    собирается успешно — а не падает с NotImplementedError."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "y")
    monkeypatch.setenv("OLLAMA_URL", "http://x")
    p = create_provider({})
    assert isinstance(p, ClaudeCLIProvider)


def test_autodetect_openai_second(monkeypatch):
    """OPENAI_API_KEY → openai. После E6.4 провайдер собирается, если
    задана `model`; без `model` падаем с LLMConfigError (а не уходим
    в ollama). Сам факт выбора openai проверяем тем, что ошибка про
    'model', а не про Ollama-URL."""
    monkeypatch.setenv("OPENAI_API_KEY", "y")
    monkeypatch.setenv("OLLAMA_URL", "http://x")
    with pytest.raises(LLMConfigError, match="model"):
        create_provider({})


def test_autodetect_ollama_third(monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", "http://x")
    with pytest.raises(NotImplementedError, match="E6.5"):
        create_provider({})


def test_autodetect_nothing_raises_config_error():
    with pytest.raises(LLMConfigError, match="No LLM provider available"):
        create_provider({})


def test_explicit_llm_overrides_autodetect(monkeypatch):
    """Явный `llm: mock` должен выиграть у env."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    p = create_provider({"llm": "mock"})
    assert isinstance(p, MockProvider)


def test_auto_keyword_triggers_autodetect(monkeypatch):
    """`llm:auto` запускает auto-detect. OPENAI_API_KEY → openai;
    без `model` падаем с LLMConfigError из E6.4-провайдера."""
    monkeypatch.setenv("OPENAI_API_KEY", "y")
    with pytest.raises(LLMConfigError, match="model"):
        create_provider({"llm": "auto"})


# ---------------------------------------------------------------------------
# MockProvider.invoke
# ---------------------------------------------------------------------------


def test_mock_invoke_returns_text():
    p = MockProvider(text="привет")
    resp = run(p.invoke(messages=[Message("user", "hi")]))
    assert isinstance(resp, LLMResponse)
    assert len(resp.content) == 1
    assert isinstance(resp.content[0], TextBlock)
    assert resp.content[0].text == "привет"
    assert resp.stop_reason == "end_turn"
    assert resp.model == "mock-1"
    assert isinstance(resp.usage, Usage)


def test_mock_invoke_returns_tool_use_block():
    tool_block = ToolUseBlock(id="toolu_1", name="ping", input={"x": 1})
    p = MockProvider(content=[tool_block], stop_reason="tool_use")
    resp = run(p.invoke(messages=[Message("user", "do it")]))
    assert resp.stop_reason == "tool_use"
    assert resp.content == [tool_block]


def test_mock_records_calls():
    p = MockProvider()
    tool = Tool(name="t", description="d", input_schema={"type": "object"})
    msgs = [Message("user", "ping")]
    run(p.invoke(messages=msgs, tools=[tool], system_prompt="sys"))
    assert len(p.calls) == 1
    call = p.calls[0]
    assert call["method"] == "invoke"
    assert call["messages"] == msgs
    assert call["tools"] == [tool]
    assert call["system_prompt"] == "sys"


# ---------------------------------------------------------------------------
# MockProvider.stream
# ---------------------------------------------------------------------------


def test_mock_stream_yields_text_deltas_then_stop():
    p = MockProvider(text="привет мир")
    chunks = run(_drain(p.stream(messages=[Message("user", "hi")])))
    # 2 слова → 2 TextDelta + финальный MessageStop.
    assert len(chunks) == 3
    assert isinstance(chunks[0], TextDelta)
    assert isinstance(chunks[1], TextDelta)
    assert isinstance(chunks[-1], MessageStop)
    # Конкатенация дельт восстанавливает исходный текст.
    accumulated = "".join(
        c.text for c in chunks if isinstance(c, TextDelta)
    )
    assert accumulated == "привет мир"


def test_mock_stream_tool_use_emits_start_delta_end():
    block = ToolUseBlock(id="toolu_42", name="ping", input={"a": 1})
    p = MockProvider(content=[block], stop_reason="tool_use")
    chunks = run(_drain(p.stream(messages=[Message("user", "go")])))
    types = [type(c).__name__ for c in chunks]
    assert types == [
        "ToolUseStart",
        "ToolUseDelta",
        "ToolUseEnd",
        "MessageStop",
    ]
    assert isinstance(chunks[0], ToolUseStart) and chunks[0].id == "toolu_42"
    assert isinstance(chunks[2], ToolUseEnd) and chunks[2].input == {"a": 1}
    assert chunks[-1].stop_reason == "tool_use"  # type: ignore[union-attr]


def test_mock_stream_respects_explicit_chunks():
    """Если в MockProvider передали свой chunks — стрим отдаёт ровно его."""
    custom = [TextDelta(text="a"), TextDelta(text="b")]
    p = MockProvider(chunks=custom)
    chunks = run(_drain(p.stream(messages=[Message("user", "x")])))
    assert chunks == custom


def test_mock_stream_records_call():
    p = MockProvider()
    run(_drain(p.stream(messages=[Message("user", "x")], system_prompt="s")))
    assert p.calls[0]["method"] == "stream"
    assert p.calls[0]["system_prompt"] == "s"


# ---------------------------------------------------------------------------
# Dataclasses sanity (frozen=True по ADR-001)
# ---------------------------------------------------------------------------


def test_message_is_frozen():
    m = Message(role="user", content="hi")
    with pytest.raises(Exception):
        m.role = "assistant"  # type: ignore[misc]


def test_tool_is_frozen():
    t = Tool(name="t", description="d", input_schema={})
    with pytest.raises(Exception):
        t.name = "other"  # type: ignore[misc]

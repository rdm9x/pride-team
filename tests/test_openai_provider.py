"""Тесты `llm.openai_provider.OpenAIProvider` (задача E6.4).

Покрывают acceptance:

* invoke с text-only ответом;
* invoke с tool_calls в ответе → собирается `ToolUseBlock`;
* маппинг `ToolResultBlock` → OpenAI tool-сообщение;
* `LLMConfigError`, если api_key пуст и env-переменная не задана;
* `LLMTransportError`, если SDK кидает сетевую ошибку;
* `stream()` собирает `TextDelta` и `ToolUseStart/Delta/End` корректно;
* factory `create_provider({"llm":"openai", ...})` возвращает наш класс.

Реальный `openai` SDK не дергаем — клиент подсовываем как mock.
Используем `unittest.mock`, без зависимости от `pytest-mock`.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from llm import (
    LLMConfigError,
    LLMResponse,
    LLMTransportError,
    Message,
    MessageStop,
    OpenAIProvider,
    TextBlock,
    TextDelta,
    Tool,
    ToolResultBlock,
    ToolUseBlock,
    ToolUseDelta,
    ToolUseEnd,
    ToolUseStart,
    create_provider,
)
from llm.openai_provider import (
    _messages_to_openai,
    _tools_to_openai,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


async def _drain(stream):
    out = []
    async for chunk in stream:
        out.append(chunk)
    return out


def _make_completion(
    *,
    text: str | None = None,
    tool_calls: list[dict] | None = None,
    finish_reason: str = "stop",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    model: str = "gpt-4o",
) -> Any:
    """Слепить минимальный mock-объект, имитирующий `ChatCompletion`."""
    message = MagicMock()
    message.content = text
    if tool_calls:
        oai_calls = []
        for tc in tool_calls:
            mock_tc = MagicMock()
            mock_tc.id = tc["id"]
            mock_tc.type = "function"
            mock_tc.function = MagicMock()
            mock_tc.function.name = tc["name"]
            mock_tc.function.arguments = tc["arguments"]
            oai_calls.append(mock_tc)
        message.tool_calls = oai_calls
    else:
        message.tool_calls = None

    choice = MagicMock()
    choice.message = message
    choice.finish_reason = finish_reason

    completion = MagicMock()
    completion.choices = [choice]
    completion.model = model
    completion.usage = MagicMock()
    completion.usage.prompt_tokens = prompt_tokens
    completion.usage.completion_tokens = completion_tokens
    # Симулируем pydantic-метод; если не вызывают — не упадёт.
    completion.model_dump = lambda: {"id": "chatcmpl-test"}
    return completion


def _make_stream_chunk(
    *,
    text: str | None = None,
    tool_calls: list[dict] | None = None,
    finish_reason: str | None = None,
    model: str = "gpt-4o",
    usage: dict | None = None,
) -> Any:
    delta = MagicMock()
    delta.content = text
    if tool_calls:
        oai_calls = []
        for tc in tool_calls:
            mock_tc = MagicMock()
            mock_tc.index = tc.get("index", 0)
            mock_tc.id = tc.get("id")
            if "name" in tc or "arguments" in tc:
                mock_tc.function = MagicMock()
                mock_tc.function.name = tc.get("name")
                mock_tc.function.arguments = tc.get("arguments")
            else:
                mock_tc.function = None
            oai_calls.append(mock_tc)
        delta.tool_calls = oai_calls
    else:
        delta.tool_calls = None

    choice = MagicMock()
    choice.delta = delta
    choice.finish_reason = finish_reason

    chunk = MagicMock()
    chunk.choices = [choice]
    chunk.model = model
    if usage is not None:
        chunk.usage = MagicMock()
        chunk.usage.prompt_tokens = usage.get("prompt_tokens", 0)
        chunk.usage.completion_tokens = usage.get("completion_tokens", 0)
    else:
        chunk.usage = None
    return chunk


def _make_client(create_result):
    """Mock OpenAI-клиент. `create_result` — что вернуть из create().

    Если `create_result` — Exception, он будет брошен.
    """
    client = MagicMock()
    if isinstance(create_result, Exception):
        client.chat.completions.create.side_effect = create_result
    else:
        client.chat.completions.create.return_value = create_result
    return client


@pytest.fixture(autouse=True)
def _clean_openai_env(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


# ---------------------------------------------------------------------------
# constructor / config
# ---------------------------------------------------------------------------


def test_openai_provider_requires_api_key_when_no_env():
    """LLMConfigError если ни api_key, ни OPENAI_API_KEY."""
    with pytest.raises(LLMConfigError, match="OPENAI_API_KEY"):
        OpenAIProvider(model="gpt-4o")


def test_openai_provider_accepts_explicit_api_key():
    p = OpenAIProvider(model="gpt-4o", api_key="sk-explicit")
    assert p.model == "gpt-4o"


def test_openai_provider_accepts_env_api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    p = OpenAIProvider(model="gpt-4o-mini")
    assert p.model == "gpt-4o-mini"


def test_openai_provider_accepts_injected_client():
    """Если передан `client`, api_key/env не проверяются (тестовый путь)."""
    fake = MagicMock()
    p = OpenAIProvider(model="gpt-4o", client=fake)
    assert p._client is fake


# ---------------------------------------------------------------------------
# invoke — text-only
# ---------------------------------------------------------------------------


def test_invoke_text_only_response():
    completion = _make_completion(
        text="привет, мир",
        finish_reason="stop",
        prompt_tokens=12,
        completion_tokens=4,
        model="gpt-4o-2024-08-06",
    )
    client = _make_client(completion)
    p = OpenAIProvider(model="gpt-4o", client=client)

    resp: LLMResponse = run(
        p.invoke(messages=[Message("user", "привет")])
    )
    assert isinstance(resp, LLMResponse)
    assert len(resp.content) == 1
    assert isinstance(resp.content[0], TextBlock)
    assert resp.content[0].text == "привет, мир"
    assert resp.stop_reason == "end_turn"
    assert resp.usage.input_tokens == 12
    assert resp.usage.output_tokens == 4
    assert resp.model == "gpt-4o-2024-08-06"
    # SDK должен был быть вызван ровно один раз с нужным model.
    client.chat.completions.create.assert_called_once()
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "gpt-4o"
    assert kwargs["messages"] == [{"role": "user", "content": "привет"}]
    assert "tools" not in kwargs  # tools не передавали


def test_invoke_passes_system_prompt_first():
    completion = _make_completion(text="ok")
    client = _make_client(completion)
    p = OpenAIProvider(model="gpt-4o", client=client)
    run(
        p.invoke(
            messages=[Message("user", "hi")],
            system_prompt="ты бот",
        )
    )
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["messages"][0] == {"role": "system", "content": "ты бот"}
    assert kwargs["messages"][1] == {"role": "user", "content": "hi"}


# ---------------------------------------------------------------------------
# invoke — tool_calls
# ---------------------------------------------------------------------------


def test_invoke_with_tool_calls_response():
    completion = _make_completion(
        text=None,
        tool_calls=[
            {
                "id": "call_abc123",
                "name": "get_weather",
                "arguments": json.dumps({"city": "Москва"}),
            }
        ],
        finish_reason="tool_calls",
    )
    client = _make_client(completion)
    p = OpenAIProvider(model="gpt-4o", client=client)

    tool = Tool(
        name="get_weather",
        description="Прогноз",
        input_schema={
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    )
    resp = run(
        p.invoke(
            messages=[Message("user", "погода в москве?")],
            tools=[tool],
        )
    )
    assert resp.stop_reason == "tool_use"
    assert len(resp.content) == 1
    block = resp.content[0]
    assert isinstance(block, ToolUseBlock)
    assert block.id == "call_abc123"
    assert block.name == "get_weather"
    assert block.input == {"city": "Москва"}

    # Проверим, что инструмент ушёл в SDK в правильной OpenAI-схеме.
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Прогноз",
                "parameters": tool.input_schema,
            },
        }
    ]


def test_invoke_with_mixed_text_and_tool_calls():
    """OpenAI иногда возвращает и текст и tool_calls в одном сообщении."""
    completion = _make_completion(
        text="сейчас уточню",
        tool_calls=[
            {
                "id": "call_x",
                "name": "ping",
                "arguments": "{}",
            }
        ],
        finish_reason="tool_calls",
    )
    client = _make_client(completion)
    p = OpenAIProvider(model="gpt-4o", client=client)
    resp = run(p.invoke(messages=[Message("user", "ping")]))
    types = [type(b).__name__ for b in resp.content]
    assert types == ["TextBlock", "ToolUseBlock"]
    assert resp.content[1].input == {}


def test_invoke_tool_call_with_invalid_json_arguments():
    """Если SDK прислал кривой JSON в arguments — не падаем, сохраняем raw."""
    completion = _make_completion(
        text=None,
        tool_calls=[
            {
                "id": "call_x",
                "name": "ping",
                "arguments": "this is not json",
            }
        ],
        finish_reason="tool_calls",
    )
    client = _make_client(completion)
    p = OpenAIProvider(model="gpt-4o", client=client)
    resp = run(p.invoke(messages=[Message("user", "go")]))
    block = resp.content[0]
    assert isinstance(block, ToolUseBlock)
    assert block.input == {"__raw": "this is not json"}


# ---------------------------------------------------------------------------
# tool_result mapping
# ---------------------------------------------------------------------------


def test_tool_result_block_maps_to_tool_message():
    """`Message('user', [ToolResultBlock])` → отдельное OpenAI tool-сообщение."""
    completion = _make_completion(text="спасибо")
    client = _make_client(completion)
    p = OpenAIProvider(model="gpt-4o", client=client)

    messages = [
        Message("user", "погода в москве?"),
        Message(
            "assistant",
            [
                ToolUseBlock(
                    id="call_w",
                    name="get_weather",
                    input={"city": "Москва"},
                )
            ],
        ),
        Message(
            "user",
            [
                ToolResultBlock(
                    tool_use_id="call_w",
                    content="+10C, дождь",
                )
            ],
        ),
    ]
    run(p.invoke(messages=messages))

    sent = client.chat.completions.create.call_args.kwargs["messages"]
    # Ожидаем: user, assistant(tool_calls), tool.
    assert sent[0] == {"role": "user", "content": "погода в москве?"}
    assert sent[1]["role"] == "assistant"
    assert sent[1]["tool_calls"][0]["id"] == "call_w"
    assert json.loads(sent[1]["tool_calls"][0]["function"]["arguments"]) == {
        "city": "Москва"
    }
    assert sent[2] == {
        "role": "tool",
        "tool_call_id": "call_w",
        "content": "+10C, дождь",
    }


def test_tool_result_error_flag_prefixed():
    """`is_error=True` маркируется префиксом `[ERROR]` для модели."""
    completion = _make_completion(text="ok")
    client = _make_client(completion)
    p = OpenAIProvider(model="gpt-4o", client=client)

    run(
        p.invoke(
            messages=[
                Message(
                    "user",
                    [
                        ToolResultBlock(
                            tool_use_id="call_err",
                            content="boom",
                            is_error=True,
                        )
                    ],
                )
            ]
        )
    )
    sent = client.chat.completions.create.call_args.kwargs["messages"]
    assert sent[0]["role"] == "tool"
    assert sent[0]["content"].startswith("[ERROR]")


def test_tool_result_with_textblock_list_content():
    """`ToolResultBlock.content` может быть list[TextBlock] — склеиваем."""
    completion = _make_completion(text="ok")
    client = _make_client(completion)
    p = OpenAIProvider(model="gpt-4o", client=client)
    run(
        p.invoke(
            messages=[
                Message(
                    "user",
                    [
                        ToolResultBlock(
                            tool_use_id="t1",
                            content=[
                                TextBlock(text="часть-1"),
                                TextBlock(text="часть-2"),
                            ],
                        )
                    ],
                )
            ]
        )
    )
    sent = client.chat.completions.create.call_args.kwargs["messages"]
    assert sent[0]["content"] == "часть-1\nчасть-2"


# ---------------------------------------------------------------------------
# errors
# ---------------------------------------------------------------------------


def test_invoke_wraps_sdk_error_in_transport_error():
    client = _make_client(RuntimeError("connection refused"))
    p = OpenAIProvider(model="gpt-4o", client=client)
    with pytest.raises(LLMTransportError, match="connection refused"):
        run(p.invoke(messages=[Message("user", "hi")]))


def test_invoke_raises_when_no_choices():
    completion = MagicMock()
    completion.choices = []
    completion.model = "gpt-4o"
    completion.usage = None
    client = _make_client(completion)
    p = OpenAIProvider(model="gpt-4o", client=client)
    with pytest.raises(LLMTransportError, match="choice"):
        run(p.invoke(messages=[Message("user", "hi")]))


# ---------------------------------------------------------------------------
# stream
# ---------------------------------------------------------------------------


def test_stream_yields_text_deltas_and_stop():
    chunks_in = [
        _make_stream_chunk(text="при"),
        _make_stream_chunk(text="вет"),
        _make_stream_chunk(
            text=None,
            finish_reason="stop",
            usage={"prompt_tokens": 5, "completion_tokens": 2},
        ),
    ]
    client = _make_client(iter(chunks_in))
    p = OpenAIProvider(model="gpt-4o", client=client)

    chunks = run(_drain(p.stream(messages=[Message("user", "hi")])))
    texts = [c.text for c in chunks if isinstance(c, TextDelta)]
    assert "".join(texts) == "привет"
    assert isinstance(chunks[-1], MessageStop)
    assert chunks[-1].stop_reason == "end_turn"
    assert chunks[-1].usage.input_tokens == 5
    assert chunks[-1].usage.output_tokens == 2


def test_stream_yields_tool_use_lifecycle():
    """Стрим tool_calls: ToolUseStart → ToolUseDelta+ → ToolUseEnd → MessageStop."""
    chunks_in = [
        _make_stream_chunk(
            tool_calls=[
                {
                    "index": 0,
                    "id": "call_a",
                    "name": "ping",
                    "arguments": '{"x": ',
                }
            ]
        ),
        _make_stream_chunk(
            tool_calls=[
                {
                    "index": 0,
                    "arguments": "1}",
                }
            ]
        ),
        _make_stream_chunk(finish_reason="tool_calls"),
    ]
    client = _make_client(iter(chunks_in))
    p = OpenAIProvider(model="gpt-4o", client=client)

    out = run(_drain(p.stream(messages=[Message("user", "go")])))
    types = [type(c).__name__ for c in out]
    assert "ToolUseStart" in types
    assert "ToolUseEnd" in types
    assert types[-1] == "MessageStop"
    end_block = next(c for c in out if isinstance(c, ToolUseEnd))
    assert end_block.input == {"x": 1}
    start_block = next(c for c in out if isinstance(c, ToolUseStart))
    assert start_block.id == "call_a"
    assert start_block.name == "ping"
    stop = out[-1]
    assert isinstance(stop, MessageStop)
    assert stop.stop_reason == "tool_use"


def test_stream_wraps_create_error_in_transport_error():
    client = _make_client(RuntimeError("nope"))
    p = OpenAIProvider(model="gpt-4o", client=client)
    with pytest.raises(LLMTransportError, match="nope"):
        run(_drain(p.stream(messages=[Message("user", "hi")])))


# ---------------------------------------------------------------------------
# factory integration
# ---------------------------------------------------------------------------


def test_factory_builds_openai_provider(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    p = create_provider({"llm": "openai", "model": "gpt-4o"})
    assert isinstance(p, OpenAIProvider)
    assert p.model == "gpt-4o"


def test_factory_honors_custom_api_key_env(monkeypatch):
    monkeypatch.setenv("MY_OPENAI", "sk-custom")
    p = create_provider(
        {"llm": "openai", "model": "gpt-4o", "api_key_env": "MY_OPENAI"}
    )
    assert isinstance(p, OpenAIProvider)


def test_factory_propagates_missing_api_key(monkeypatch):
    """Если env-переменной нет — provider бросает LLMConfigError."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(LLMConfigError):
        create_provider({"llm": "openai", "model": "gpt-4o"})


# ---------------------------------------------------------------------------
# mapping helpers (мелочи)
# ---------------------------------------------------------------------------


def test_messages_to_openai_string_content():
    out = _messages_to_openai([Message("user", "hi")], None)
    assert out == [{"role": "user", "content": "hi"}]


def test_messages_to_openai_assistant_text_and_tool_use():
    msg = Message(
        "assistant",
        [
            TextBlock(text="думаю"),
            ToolUseBlock(id="t1", name="ping", input={"a": 1}),
        ],
    )
    out = _messages_to_openai([msg], None)
    assert out[0]["role"] == "assistant"
    assert out[0]["content"] == "думаю"
    assert out[0]["tool_calls"][0]["id"] == "t1"
    args = json.loads(out[0]["tool_calls"][0]["function"]["arguments"])
    assert args == {"a": 1}


def test_tools_to_openai_empty_returns_empty_list():
    assert _tools_to_openai(None) == []
    assert _tools_to_openai([]) == []


def test_tools_to_openai_wraps_in_function_schema():
    t = Tool(name="x", description="d", input_schema={"type": "object"})
    out = _tools_to_openai([t])
    assert out == [
        {
            "type": "function",
            "function": {
                "name": "x",
                "description": "d",
                "parameters": {"type": "object"},
            },
        }
    ]

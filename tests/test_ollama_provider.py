"""Тесты `llm.ollama_provider.OllamaProvider` (задача E6.5).

Покрывают acceptance:

* `create_provider({"llm":"ollama","model":"llama3.1"})` возвращает OllamaProvider;
* `invoke` с text-only ответом;
* `invoke` с tool-call JSON в ответе → собирается `ToolUseBlock`;
* Fallback при невалидном JSON в ответе → не падает, возвращает `TextBlock`;
* `invoke` пробрасывает `LLMTransportError` при HTTP-ошибке;
* `stream()` собирает `TextDelta` и `MessageStop` корректно;
* `stream()` с tool-call → `ToolUseStart` + `ToolUseEnd` + `MessageStop`;
* `stream()` пробрасывает `LLMTransportError` при HTTP-ошибке;
* factory подхватывает `OLLAMA_URL` из env;
* helper `_build_system` вставляет tool-инструкцию;
* helper `_messages_to_ollama` правильно сериализует разные типы блоков.

Реальный Ollama не нужен — httpx мокируем через `unittest.mock.patch`.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llm import (
    LLMResponse,
    LLMTransportError,
    Message,
    MessageStop,
    OllamaProvider,
    TextBlock,
    TextDelta,
    Tool,
    ToolResultBlock,
    ToolUseBlock,
    ToolUseEnd,
    ToolUseStart,
    create_provider,
)
from llm.ollama_provider import (
    _build_system,
    _messages_to_ollama,
    _try_parse_tool_call,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def run(coro):
    """Запустить корутину в новом event loop (без pytest-asyncio)."""
    return asyncio.new_event_loop().run_until_complete(coro)


async def _drain(agen):
    """Собрать все элементы из async-генератора в список."""
    out = []
    async for item in agen:
        out.append(item)
    return out


def _ollama_response(
    content: str = "привет",
    model: str = "llama3.1",
    prompt_eval_count: int = 10,
    eval_count: int = 5,
) -> dict:
    """Минимальный словарь, имитирующий ответ Ollama `/api/chat` (stream=false)."""
    return {
        "model": model,
        "message": {"role": "assistant", "content": content},
        "done": True,
        "prompt_eval_count": prompt_eval_count,
        "eval_count": eval_count,
    }


def _stream_lines(
    *text_parts: str,
    model: str = "llama3.1",
    prompt_eval_count: int = 8,
    eval_count: int = 3,
) -> list[str]:
    """Сгенерировать NDJSON-строки как Ollama шлёт при stream=true."""
    lines = []
    for i, part in enumerate(text_parts):
        lines.append(
            json.dumps(
                {
                    "model": model,
                    "message": {"role": "assistant", "content": part},
                    "done": False,
                }
            )
        )
    # финальный чанк
    lines.append(
        json.dumps(
            {
                "model": model,
                "message": {"role": "assistant", "content": ""},
                "done": True,
                "prompt_eval_count": prompt_eval_count,
                "eval_count": eval_count,
            }
        )
    )
    return lines


class _FakeAsyncIterator:
    """Обёртка над list[str], реализующая async-итератор для aiter_lines()."""

    def __init__(self, lines: list[str]) -> None:
        self._iter = iter(lines)

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


def _make_async_client_mock(
    *,
    invoke_response: dict | None = None,
    invoke_error: Exception | None = None,
    stream_lines: list[str] | None = None,
    stream_error: Exception | None = None,
) -> MagicMock:
    """Создать mock `httpx.AsyncClient`, который ведёт себя как context manager.

    Поддерживает оба режима:
      * `invoke_response`: для `client.post(...).json()` — не-стриминговый вызов.
      * `stream_lines`: для `client.stream(...)` — стриминговый вызов (NDJSON).
    """
    mock_client = MagicMock()

    if invoke_error is not None:
        post_mock = AsyncMock(side_effect=invoke_error)
        mock_client.post = post_mock
    elif invoke_response is not None:
        # mock для await client.post(...)
        resp_mock = MagicMock()
        resp_mock.raise_for_status = MagicMock()
        resp_mock.json = MagicMock(return_value=invoke_response)
        mock_client.post = AsyncMock(return_value=resp_mock)

    if stream_error is not None:
        # client.stream() как async context manager бросает ошибку.
        stream_cm = MagicMock()
        stream_cm.__aenter__ = AsyncMock(side_effect=stream_error)
        stream_cm.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(return_value=stream_cm)
    elif stream_lines is not None:
        # client.stream() как async context manager отдаёт resp с aiter_lines.
        resp_mock = MagicMock()
        resp_mock.raise_for_status = MagicMock()
        resp_mock.aiter_lines = MagicMock(
            return_value=_FakeAsyncIterator(stream_lines)
        )
        stream_cm = MagicMock()
        stream_cm.__aenter__ = AsyncMock(return_value=resp_mock)
        stream_cm.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(return_value=stream_cm)

    # AsyncClient сам — context manager.
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


# ---------------------------------------------------------------------------
# Конструктор
# ---------------------------------------------------------------------------


def test_constructor_defaults():
    p = OllamaProvider(model="llama3.1")
    assert p.model == "llama3.1"
    assert p._base_url == "http://localhost:11434"


def test_constructor_custom_base_url():
    p = OllamaProvider(model="mistral", base_url="http://gpu-box:11434")
    assert p._base_url == "http://gpu-box:11434"


def test_constructor_strips_trailing_slash():
    p = OllamaProvider(model="m", base_url="http://localhost:11434/")
    assert p._base_url == "http://localhost:11434"


# ---------------------------------------------------------------------------
# invoke — text-only
# ---------------------------------------------------------------------------


def test_invoke_text_only_response():
    data = _ollama_response("Привет, мир!", prompt_eval_count=12, eval_count=4)
    ctx = _make_async_client_mock(invoke_response=data)

    with patch("httpx.AsyncClient", return_value=ctx):
        p = OllamaProvider(model="llama3.1")
        resp: LLMResponse = run(p.invoke([Message("user", "привет")]))

    assert isinstance(resp, LLMResponse)
    assert len(resp.content) == 1
    assert isinstance(resp.content[0], TextBlock)
    assert resp.content[0].text == "Привет, мир!"
    assert resp.stop_reason == "end_turn"
    assert resp.usage.input_tokens == 12
    assert resp.usage.output_tokens == 4
    assert resp.model == "llama3.1"


def test_invoke_passes_system_prompt():
    data = _ollama_response("ok")
    ctx = _make_async_client_mock(invoke_response=data)

    with patch("httpx.AsyncClient", return_value=ctx):
        p = OllamaProvider(model="llama3.1")
        run(
            p.invoke(
                messages=[Message("user", "hi")],
                system_prompt="ты бот",
            )
        )

    # Проверяем тело запроса.
    post_call = ctx.__aenter__.return_value.post
    body = post_call.call_args.kwargs["json"]
    assert body["messages"][0] == {"role": "system", "content": "ты бот"}
    assert body["stream"] is False


# ---------------------------------------------------------------------------
# invoke — tool calling (JSON-prompting)
# ---------------------------------------------------------------------------


def test_invoke_tool_call_response():
    """Если модель ответила JSON tool-call — получаем ToolUseBlock."""
    tool_json = json.dumps({"tool": "get_weather", "args": {"city": "Москва"}})
    data = _ollama_response(tool_json)
    ctx = _make_async_client_mock(invoke_response=data)

    tool = Tool(
        name="get_weather",
        description="Прогноз погоды",
        input_schema={"type": "object", "properties": {"city": {"type": "string"}}},
    )
    with patch("httpx.AsyncClient", return_value=ctx):
        p = OllamaProvider(model="llama3.1")
        resp = run(p.invoke(messages=[Message("user", "погода?")], tools=[tool]))

    assert resp.stop_reason == "tool_use"
    assert len(resp.content) == 1
    block = resp.content[0]
    assert isinstance(block, ToolUseBlock)
    assert block.name == "get_weather"
    assert block.input == {"city": "Москва"}
    assert block.id.startswith("toolu_")


def test_invoke_tool_call_with_surrounding_text():
    """Модель добавила текст вокруг JSON — всё равно парсим."""
    tool_json = (
        'Конечно! {"tool": "ping", "args": {"x": 1}} — вызову инструмент.'
    )
    data = _ollama_response(tool_json)
    ctx = _make_async_client_mock(invoke_response=data)

    tool = Tool(name="ping", description="ping", input_schema={"type": "object"})
    with patch("httpx.AsyncClient", return_value=ctx):
        p = OllamaProvider(model="llama3.1")
        resp = run(p.invoke(messages=[Message("user", "ping")], tools=[tool]))

    block = resp.content[0]
    assert isinstance(block, ToolUseBlock)
    assert block.name == "ping"
    assert block.input == {"x": 1}


def test_invoke_invalid_json_fallback_to_text():
    """При невалидном JSON — не падаем, возвращаем TextBlock."""
    bad_response = "это не JSON {"
    data = _ollama_response(bad_response)
    ctx = _make_async_client_mock(invoke_response=data)

    tool = Tool(name="ping", description="ping", input_schema={"type": "object"})
    with patch("httpx.AsyncClient", return_value=ctx):
        p = OllamaProvider(model="llama3.1")
        resp = run(p.invoke(messages=[Message("user", "go")], tools=[tool]))

    assert resp.stop_reason == "end_turn"
    assert len(resp.content) == 1
    assert isinstance(resp.content[0], TextBlock)
    assert resp.content[0].text == bad_response


def test_invoke_no_tools_no_tool_parsing():
    """Без списка tools — JSON в ответе не парсится как tool-call."""
    data = _ollama_response('{"tool": "ping", "args": {}}')
    ctx = _make_async_client_mock(invoke_response=data)

    with patch("httpx.AsyncClient", return_value=ctx):
        p = OllamaProvider(model="llama3.1")
        resp = run(p.invoke(messages=[Message("user", "go")]))  # tools=None

    # Без tools — возвращаем как обычный текст.
    assert resp.stop_reason == "end_turn"
    assert isinstance(resp.content[0], TextBlock)


# ---------------------------------------------------------------------------
# invoke — errors
# ---------------------------------------------------------------------------


def test_invoke_http_error_raises_transport_error():
    import httpx as _httpx

    ctx = _make_async_client_mock(
        invoke_error=_httpx.ConnectError("connection refused")
    )
    with patch("httpx.AsyncClient", return_value=ctx):
        p = OllamaProvider(model="llama3.1")
        with pytest.raises(LLMTransportError, match="connection refused"):
            run(p.invoke(messages=[Message("user", "hi")]))


def test_invoke_generic_error_raises_transport_error():
    ctx = _make_async_client_mock(invoke_error=RuntimeError("boom"))
    with patch("httpx.AsyncClient", return_value=ctx):
        p = OllamaProvider(model="llama3.1")
        with pytest.raises(LLMTransportError, match="boom"):
            run(p.invoke(messages=[Message("user", "hi")]))


# ---------------------------------------------------------------------------
# stream — text
# ---------------------------------------------------------------------------


def test_stream_text_yields_text_delta_and_stop():
    lines = _stream_lines("при", "вет", prompt_eval_count=6, eval_count=2)
    ctx = _make_async_client_mock(stream_lines=lines)

    with patch("httpx.AsyncClient", return_value=ctx):
        p = OllamaProvider(model="llama3.1")
        chunks = run(_drain(p.stream(messages=[Message("user", "hi")])))

    texts = [c.text for c in chunks if isinstance(c, TextDelta)]
    assert "".join(texts) == "привет"
    assert isinstance(chunks[-1], MessageStop)
    assert chunks[-1].stop_reason == "end_turn"
    assert chunks[-1].usage.input_tokens == 6
    assert chunks[-1].usage.output_tokens == 2


def test_stream_empty_response_yields_only_stop():
    lines = _stream_lines()  # нет текстовых чанков, только финальный done
    ctx = _make_async_client_mock(stream_lines=lines)

    with patch("httpx.AsyncClient", return_value=ctx):
        p = OllamaProvider(model="llama3.1")
        chunks = run(_drain(p.stream(messages=[Message("user", "hi")])))

    assert any(isinstance(c, MessageStop) for c in chunks)
    assert not any(isinstance(c, TextDelta) for c in chunks)


# ---------------------------------------------------------------------------
# stream — tool calling
# ---------------------------------------------------------------------------


def test_stream_tool_call_yields_tool_lifecycle():
    """Стрим с tool-call JSON → ToolUseStart + ToolUseEnd + MessageStop."""
    tool_json = json.dumps({"tool": "ping", "args": {"x": 42}})
    lines = _stream_lines(tool_json)
    ctx = _make_async_client_mock(stream_lines=lines)

    tool = Tool(name="ping", description="ping", input_schema={"type": "object"})
    with patch("httpx.AsyncClient", return_value=ctx):
        p = OllamaProvider(model="llama3.1")
        chunks = run(_drain(p.stream(messages=[Message("user", "go")], tools=[tool])))

    types = [type(c).__name__ for c in chunks]
    assert "ToolUseStart" in types
    assert "ToolUseEnd" in types
    assert types[-1] == "MessageStop"

    start = next(c for c in chunks if isinstance(c, ToolUseStart))
    assert start.name == "ping"
    end = next(c for c in chunks if isinstance(c, ToolUseEnd))
    assert end.input == {"x": 42}
    stop = chunks[-1]
    assert isinstance(stop, MessageStop)
    assert stop.stop_reason == "tool_use"


def test_stream_invalid_json_tool_fallback():
    """Стрим с невалидным JSON при наличии tools → TextDelta, не падаем."""
    lines = _stream_lines("не JSON {")
    ctx = _make_async_client_mock(stream_lines=lines)

    tool = Tool(name="ping", description="ping", input_schema={"type": "object"})
    with patch("httpx.AsyncClient", return_value=ctx):
        p = OllamaProvider(model="llama3.1")
        chunks = run(_drain(p.stream(messages=[Message("user", "go")], tools=[tool])))

    assert any(isinstance(c, TextDelta) for c in chunks)
    assert isinstance(chunks[-1], MessageStop)
    assert chunks[-1].stop_reason == "end_turn"


# ---------------------------------------------------------------------------
# stream — errors
# ---------------------------------------------------------------------------


def test_stream_http_error_raises_transport_error():
    import httpx as _httpx

    ctx = _make_async_client_mock(
        stream_error=_httpx.ConnectError("refused")
    )
    with patch("httpx.AsyncClient", return_value=ctx):
        p = OllamaProvider(model="llama3.1")
        with pytest.raises(LLMTransportError, match="refused"):
            run(_drain(p.stream(messages=[Message("user", "hi")])))


# ---------------------------------------------------------------------------
# factory integration
# ---------------------------------------------------------------------------


def test_factory_builds_ollama_provider():
    p = create_provider({"llm": "ollama", "model": "llama3.1"})
    assert isinstance(p, OllamaProvider)
    assert p.model == "llama3.1"


def test_factory_default_model():
    """Если model не задан — подставляется дефолт llama3.1."""
    p = create_provider({"llm": "ollama"})
    assert isinstance(p, OllamaProvider)
    assert p.model == "llama3.1"


def test_factory_uses_ollama_url_env(monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", "http://gpu:11434")
    p = create_provider({"llm": "ollama", "model": "mistral"})
    assert isinstance(p, OllamaProvider)
    assert p._base_url == "http://gpu:11434"


def test_factory_extras_base_url():
    p = create_provider(
        {"llm": "ollama", "model": "qwen2", "extras": {"base_url": "http://box:11434"}}
    )
    assert p._base_url == "http://box:11434"


def test_factory_extras_timeout():
    p = create_provider(
        {"llm": "ollama", "model": "llama3.1", "extras": {"timeout": "60"}}
    )
    assert p._timeout == 60.0


# ---------------------------------------------------------------------------
# helper: _build_system
# ---------------------------------------------------------------------------


def test_build_system_no_tools_returns_original():
    assert _build_system("system prompt", None) == "system prompt"
    assert _build_system(None, None) is None
    assert _build_system(None, []) is None


def test_build_system_with_tools_includes_instruction():
    tools = [
        Tool(
            name="get_weather",
            description="Прогноз",
            input_schema={"type": "object"},
        )
    ]
    result = _build_system(None, tools)
    assert result is not None
    assert "get_weather" in result
    assert '{"tool":' in result or '"tool"' in result
    assert "args" in result


def test_build_system_prepends_original_system():
    tools = [Tool(name="x", description="d", input_schema={"type": "object"})]
    result = _build_system("ты бот", tools)
    assert result is not None
    assert result.startswith("ты бот")
    assert "x" in result


# ---------------------------------------------------------------------------
# helper: _messages_to_ollama
# ---------------------------------------------------------------------------


def test_messages_to_ollama_string_content():
    out = _messages_to_ollama([Message("user", "hi")], None)
    assert out == [{"role": "user", "content": "hi"}]


def test_messages_to_ollama_system_first():
    out = _messages_to_ollama([Message("user", "hi")], "sys")
    assert out[0] == {"role": "system", "content": "sys"}
    assert out[1] == {"role": "user", "content": "hi"}


def test_messages_to_ollama_tool_use_block_serialized():
    msg = Message(
        "assistant",
        [
            TextBlock(text="ок"),
            ToolUseBlock(id="t1", name="ping", input={"x": 1}),
        ],
    )
    out = _messages_to_ollama([msg], None)
    content = out[0]["content"]
    assert "ок" in content
    # ToolUseBlock сериализуется в JSON.
    assert '"ping"' in content or "ping" in content


def test_messages_to_ollama_tool_result_block():
    msg = Message(
        "user",
        [
            ToolResultBlock(
                tool_use_id="call_w",
                content="sunny",
            )
        ],
    )
    out = _messages_to_ollama([msg], None)
    assert out[0]["role"] == "user"
    assert "sunny" in out[0]["content"]


def test_messages_to_ollama_tool_result_error_flag():
    msg = Message(
        "user",
        [ToolResultBlock(tool_use_id="t1", content="boom", is_error=True)],
    )
    out = _messages_to_ollama([msg], None)
    assert "[ERROR]" in out[0]["content"]


# ---------------------------------------------------------------------------
# helper: _try_parse_tool_call
# ---------------------------------------------------------------------------


def test_try_parse_tool_call_valid_json():
    text = json.dumps({"tool": "ping", "args": {"a": 1}})
    block = _try_parse_tool_call(text)
    assert block is not None
    assert block.name == "ping"
    assert block.input == {"a": 1}
    assert block.id.startswith("toolu_")


def test_try_parse_tool_call_json_embedded_in_text():
    text = 'Конечно! {"tool": "search", "args": {"q": "test"}} — готово.'
    block = _try_parse_tool_call(text)
    assert block is not None
    assert block.name == "search"
    assert block.input == {"q": "test"}


def test_try_parse_tool_call_invalid_json_returns_none():
    assert _try_parse_tool_call("это обычный текст") is None
    assert _try_parse_tool_call("{ не json }") is None


def test_try_parse_tool_call_json_without_tool_key():
    # Валидный JSON, но не tool-call.
    assert _try_parse_tool_call('{"key": "value"}') is None


def test_try_parse_tool_call_args_not_dict_returns_empty():
    text = json.dumps({"tool": "ping", "args": "bad"})
    block = _try_parse_tool_call(text)
    assert block is not None
    # args не dict — должны вернуть пустой dict.
    assert block.input == {}

"""Тесты `llm.claude_cli_provider.ClaudeCLIProvider` (задача E6.3).

Subprocess к настоящему `claude` не делаем — это бы потребовало живого
бинаря и стоило денег. Везде мокаем `asyncio.create_subprocess_exec`
тонкой фейковой имплементацией, которая отдаёт заранее заданный
stdout/stderr/returncode.

Также покрываем чистые helper'ы (`_build_prompt`, `_events_to_chunks`)
напрямую — они идемпотентны и не требуют процесса.
"""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

import pytest

from llm import (
    ClaudeCLIProvider,
    LLMConfigError,
    LLMResponse,
    LLMTransportError,
    Message,
    MessageStop,
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
from llm.claude_cli_provider import (
    _build_prompt,
    _events_to_chunks,
    _normalize_stop_reason,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def run(coro):
    """Запустить корутину в чистом event-loop'е."""
    return asyncio.new_event_loop().run_until_complete(coro)


async def _drain(stream: AsyncIterator) -> list:
    out: list = []
    async for chunk in stream:
        out.append(chunk)
    return out


class _FakeStream:
    """Имитирует proc.stdout.readline() для async-subprocess."""

    def __init__(self, lines: list[bytes]) -> None:
        self._lines = list(lines)

    async def readline(self) -> bytes:
        if not self._lines:
            return b""
        return self._lines.pop(0)

    async def read(self) -> bytes:
        out = b"".join(self._lines)
        self._lines.clear()
        return out


class _FakeProc:
    """Фейк subprocess.Process с заранее заданным выводом."""

    def __init__(
        self,
        stdout: bytes = b"",
        stderr: bytes = b"",
        stream_lines: list[bytes] | None = None,
        returncode: int = 0,
    ) -> None:
        self._stdout_blob = stdout
        self._stderr_blob = stderr
        self.returncode = returncode
        self.stdout = _FakeStream(stream_lines or [])
        self.stderr = _FakeStream([stderr] if stderr else [])
        self.last_cmd: tuple = ()

    async def communicate(self):
        return self._stdout_blob, self._stderr_blob

    async def wait(self):
        return self.returncode


def _patch_subprocess(monkeypatch, proc: _FakeProc | Exception):
    """Подменить asyncio.create_subprocess_exec единым фейк-обработчиком.

    Если передан Exception — вместо процесса будет raise (например,
    FileNotFoundError).
    """
    calls: list[tuple] = []

    async def fake_exec(*args, **kwargs):
        calls.append(args)
        if isinstance(proc, Exception):
            raise proc
        proc.last_cmd = args
        return proc

    monkeypatch.setattr(
        "llm.claude_cli_provider.asyncio.create_subprocess_exec",
        fake_exec,
    )
    return calls


# ---------------------------------------------------------------------------
# Конструктор: валидация
# ---------------------------------------------------------------------------


def test_constructor_defaults():
    p = ClaudeCLIProvider()
    assert p.model == "claude-opus-4-7"
    assert p.allowed_tools is None
    assert p.mcp_config is None
    assert p.permission_mode == "bypassPermissions"
    assert p.cli_path == "claude"


def test_constructor_rejects_empty_model():
    with pytest.raises(LLMConfigError):
        ClaudeCLIProvider(model="   ")


def test_constructor_rejects_non_list_allowed_tools():
    with pytest.raises(LLMConfigError):
        ClaudeCLIProvider(allowed_tools="Read,Bash")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _build_prompt
# ---------------------------------------------------------------------------


def test_build_prompt_single_user_message_passes_through():
    msgs = [Message(role="user", content="привет, как дела?")]
    assert _build_prompt(msgs) == "привет, как дела?"


def test_build_prompt_multi_message_uses_tags():
    msgs = [
        Message(role="user", content="ping"),
        Message(role="assistant", content="pong"),
        Message(role="user", content="ещё раз?"),
    ]
    out = _build_prompt(msgs)
    assert "<USER>\nping\n</USER>" in out
    assert "<ASSISTANT>\npong\n</ASSISTANT>" in out
    assert out.endswith("</USER>")


def test_build_prompt_renders_tool_use_and_result_blocks():
    msgs = [
        Message(
            role="assistant",
            content=[
                TextBlock(text="буду звать инструмент"),
                ToolUseBlock(id="toolu_1", name="ping", input={"x": 1}),
            ],
        ),
        Message(
            role="user",
            content=[
                ToolResultBlock(tool_use_id="toolu_1", content="ok"),
            ],
        ),
    ]
    out = _build_prompt(msgs)
    assert "[tool_use ping id=toolu_1" in out
    assert "[tool_result id=toolu_1] ok" in out


def test_build_prompt_empty_messages():
    assert _build_prompt([]) == ""


# ---------------------------------------------------------------------------
# _events_to_chunks
# ---------------------------------------------------------------------------


def test_events_text_block_becomes_text_delta():
    ev = {
        "type": "assistant",
        "message": {
            "content": [{"type": "text", "text": "привет"}],
        },
    }
    chunks = list(_events_to_chunks(ev, "m"))
    assert chunks == [TextDelta(text="привет")]


def test_events_tool_use_becomes_start_delta_end():
    ev = {
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_42",
                    "name": "Bash",
                    "input": {"command": "ls"},
                }
            ],
        },
    }
    chunks = list(_events_to_chunks(ev, "m"))
    assert isinstance(chunks[0], ToolUseStart)
    assert chunks[0].id == "toolu_42"
    assert chunks[0].name == "Bash"
    assert isinstance(chunks[1], ToolUseDelta)
    assert json.loads(chunks[1].partial_json) == {"command": "ls"}
    assert isinstance(chunks[2], ToolUseEnd)
    assert chunks[2].input == {"command": "ls"}


def test_events_result_event_becomes_message_stop_with_usage():
    ev = {
        "type": "result",
        "model": "claude-opus-4-7",
        "usage": {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_creation_input_tokens": 10,
            "cache_read_input_tokens": 5,
        },
        "stop_reason": "end_turn",
    }
    chunks = list(_events_to_chunks(ev, "fallback"))
    assert len(chunks) == 1
    msg = chunks[0]
    assert isinstance(msg, MessageStop)
    assert msg.stop_reason == "end_turn"
    assert msg.usage == Usage(
        input_tokens=100,
        output_tokens=50,
        cache_creation_input_tokens=10,
        cache_read_input_tokens=5,
    )
    assert msg.model == "claude-opus-4-7"


def test_events_result_falls_back_to_modelusage():
    """Если ev.model нет — берём из modelUsage самую дорогую."""
    ev = {
        "type": "result",
        "modelUsage": {
            "haiku": {"costUSD": 0.001},
            "opus": {"costUSD": 0.05},
        },
    }
    chunks = list(_events_to_chunks(ev, "fallback"))
    assert isinstance(chunks[0], MessageStop)
    assert chunks[0].model == "opus"


def test_events_system_and_other_ignored():
    assert list(_events_to_chunks({"type": "system"}, "m")) == []
    assert list(_events_to_chunks({"type": "stream_event"}, "m")) == []


def test_normalize_stop_reason_passes_valid():
    assert _normalize_stop_reason("tool_use") == "tool_use"


def test_normalize_stop_reason_falls_back_to_end_turn():
    assert _normalize_stop_reason("success") == "end_turn"
    assert _normalize_stop_reason(None) == "end_turn"
    assert _normalize_stop_reason(123) == "end_turn"


# ---------------------------------------------------------------------------
# invoke()
# ---------------------------------------------------------------------------


def test_invoke_success(monkeypatch):
    fake = _FakeProc(stdout=b"hello world\n", returncode=0)
    calls = _patch_subprocess(monkeypatch, fake)

    p = ClaudeCLIProvider()
    resp = run(
        p.invoke(
            messages=[Message("user", "hi")],
            system_prompt="ты милый",
        )
    )

    assert isinstance(resp, LLMResponse)
    assert len(resp.content) == 1
    assert isinstance(resp.content[0], TextBlock)
    assert resp.content[0].text == "hello world"
    assert resp.stop_reason == "end_turn"
    assert resp.model == "claude-opus-4-7"

    # Проверяем команду: должен быть system-prompt, model, permission-mode
    # и в конце --print + сам prompt.
    cmd = list(calls[0])
    assert cmd[0] == "claude"
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "claude-opus-4-7"
    assert "--append-system-prompt" in cmd
    assert cmd[cmd.index("--append-system-prompt") + 1] == "ты милый"
    assert "--permission-mode" in cmd
    assert cmd[-2] == "--print"
    assert cmd[-1] == "hi"


def test_invoke_passes_allowed_tools_and_mcp(monkeypatch):
    fake = _FakeProc(stdout=b"ok\n", returncode=0)
    calls = _patch_subprocess(monkeypatch, fake)

    p = ClaudeCLIProvider(
        allowed_tools=["Read", "Bash"],
        mcp_config="/tmp/.mcp.json",
    )
    run(
        p.invoke(
            messages=[Message("user", "x")],
            tools=[Tool(name="Edit", description="d", input_schema={})],
        )
    )

    cmd = list(calls[0])
    assert "--mcp-config" in cmd
    assert cmd[cmd.index("--mcp-config") + 1] == "/tmp/.mcp.json"
    assert "--allowed-tools" in cmd
    tools_value = cmd[cmd.index("--allowed-tools") + 1]
    # Из конструктора + из tools-аргумента склеилось.
    assert tools_value == "Read,Bash,Edit"


def test_invoke_transport_error_when_cli_missing(monkeypatch):
    _patch_subprocess(monkeypatch, FileNotFoundError("no claude"))
    p = ClaudeCLIProvider()
    with pytest.raises(LLMTransportError, match="claude CLI not found"):
        run(p.invoke(messages=[Message("user", "hi")]))


def test_invoke_transport_error_when_nonzero_returncode(monkeypatch):
    fake = _FakeProc(stdout=b"", stderr=b"bad token", returncode=1)
    _patch_subprocess(monkeypatch, fake)
    p = ClaudeCLIProvider()
    with pytest.raises(LLMTransportError, match="exited with code 1"):
        run(p.invoke(messages=[Message("user", "hi")]))


# ---------------------------------------------------------------------------
# stream()
# ---------------------------------------------------------------------------


def test_stream_parses_ndjson_assistant_text_and_result(monkeypatch):
    lines = [
        json.dumps({"type": "system", "subtype": "init"}).encode() + b"\n",
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "привет"},
                    ]
                },
            }
        ).encode()
        + b"\n",
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_1",
                            "name": "Bash",
                            "input": {"command": "ls"},
                        }
                    ]
                },
            }
        ).encode()
        + b"\n",
        json.dumps(
            {
                "type": "result",
                "model": "claude-opus-4-7",
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 20,
                },
                "stop_reason": "end_turn",
            }
        ).encode()
        + b"\n",
    ]
    fake = _FakeProc(stream_lines=lines, returncode=0)
    calls = _patch_subprocess(monkeypatch, fake)

    p = ClaudeCLIProvider()
    chunks = run(_drain(p.stream(messages=[Message("user", "go")])))

    types = [type(c).__name__ for c in chunks]
    # system должен быть проигнорирован, всё остальное транслируется.
    assert types == [
        "TextDelta",
        "ToolUseStart",
        "ToolUseDelta",
        "ToolUseEnd",
        "MessageStop",
    ]
    assert isinstance(chunks[0], TextDelta) and chunks[0].text == "привет"
    last = chunks[-1]
    assert isinstance(last, MessageStop)
    assert last.usage.input_tokens == 10
    assert last.usage.output_tokens == 20
    assert last.model == "claude-opus-4-7"

    # И команда — со stream-флагами.
    cmd = list(calls[0])
    assert "--output-format" in cmd
    assert cmd[cmd.index("--output-format") + 1] == "stream-json"
    assert "--verbose" in cmd
    assert "--include-partial-messages" in cmd


def test_stream_invalid_json_raises_transport_error(monkeypatch):
    lines = [b"this is not json\n"]
    fake = _FakeProc(stream_lines=lines, returncode=0)
    _patch_subprocess(monkeypatch, fake)
    p = ClaudeCLIProvider()
    with pytest.raises(LLMTransportError, match="невалидный JSON"):
        run(_drain(p.stream(messages=[Message("user", "go")])))


def test_stream_emits_message_stop_even_without_result_event(monkeypatch):
    """Если CLI не прислал result — стрим всё равно должен дать MessageStop."""
    lines = [
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "text", "text": "hi"}],
                },
            }
        ).encode()
        + b"\n",
    ]
    fake = _FakeProc(stream_lines=lines, returncode=0)
    _patch_subprocess(monkeypatch, fake)
    p = ClaudeCLIProvider()
    chunks = run(_drain(p.stream(messages=[Message("user", "x")])))
    assert isinstance(chunks[-1], MessageStop)


def test_stream_transport_error_when_cli_missing(monkeypatch):
    _patch_subprocess(monkeypatch, FileNotFoundError("nope"))
    p = ClaudeCLIProvider()
    with pytest.raises(LLMTransportError, match="claude CLI not found"):
        run(_drain(p.stream(messages=[Message("user", "x")])))


def test_stream_transport_error_on_nonzero_returncode(monkeypatch):
    """Финальный rc != 0 → LLMTransportError, даже если стрим уже отдал данные."""
    lines = [
        json.dumps(
            {
                "type": "result",
                "model": "claude-opus-4-7",
                "usage": {},
                "stop_reason": "end_turn",
            }
        ).encode()
        + b"\n",
    ]
    fake = _FakeProc(
        stream_lines=lines,
        stderr=b"rate limited",
        returncode=2,
    )
    _patch_subprocess(monkeypatch, fake)
    p = ClaudeCLIProvider()
    with pytest.raises(LLMTransportError, match="exited with code 2"):
        run(_drain(p.stream(messages=[Message("user", "x")])))

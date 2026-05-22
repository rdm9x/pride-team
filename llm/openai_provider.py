"""`OpenAIProvider` — реализация `LLMProvider` поверх `openai` SDK.

ADR-001 §2.3 / §6.1 / §3 («Tool-call ID-несовместимость»). Этот провайдер:

* Принимает Anthropic-style content-blocks (`TextBlock`, `ToolUseBlock`,
  `ToolResultBlock`) и переводит их в OpenAI chat-completion формат
  (роли `user`/`assistant`/`tool`, `tool_calls`/`tool_call_id`).
* Преобразует наши `Tool` в OpenAI tool-schema
  `{"type": "function", "function": {...}}`.
* Из ответа `client.chat.completions.create(...)` собирает обратно
  `LLMResponse` с content-блоками (`TextBlock` + `ToolUseBlock`).
* Поддерживает стриминг: `stream=True` → асинхронный генератор
  `LLMChunk`'ов (`TextDelta`, `ToolUseStart/Delta/End`, `MessageStop`).
* Любую сетевую/SDK-ошибку оборачивает в `LLMTransportError`,
  ошибку конфигурации (нет API-ключа) — в `LLMConfigError`.

Импорт `openai` сделан lazy внутри методов — чтобы сам импорт `llm`
не падал, если SDK не установлен (CI без openai-deps; mock-провайдер
должен оставаться рабочим).
"""

from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator

from .base import (
    ContentBlock,
    LLMChunk,
    LLMConfigError,
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


# OpenAI finish_reason → наш StopReason (ADR-001 §2.2).
# `function_call` legacy — мапим в `tool_use` для совместимости.
_FINISH_REASON_MAP: dict[str, StopReason] = {
    "stop": "end_turn",
    "length": "max_tokens",
    "tool_calls": "tool_use",
    "function_call": "tool_use",
    "content_filter": "end_turn",
}


class OpenAIProvider(LLMProvider):
    """LLMProvider поверх `openai.OpenAI` (sync client, async-фасад).

    Args:
        model: имя модели (`gpt-4o`, `gpt-4o-mini`, …).
        api_key: API-ключ. Если `None` — берётся из `OPENAI_API_KEY` env.
        client: для тестов можно подсунуть готовый mock-клиент,
            тогда `api_key` не проверяется.
        base_url: опциональный override (для Azure/прокси).

    Raises:
        LLMConfigError: ни `api_key`, ни `OPENAI_API_KEY`, ни явный
            `client` не заданы.
    """

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        *,
        client: Any | None = None,
        base_url: str | None = None,
    ) -> None:
        self.model = model
        self._base_url = base_url
        if client is not None:
            # Тестовый путь: уже готовый OpenAI-клиент (или его mock).
            self._client = client
            self._api_key = api_key
            return

        key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY")
        if not key:
            raise LLMConfigError(
                "OpenAIProvider: не задан api_key и переменная окружения "
                "OPENAI_API_KEY пуста."
            )
        self._api_key = key
        self._client = None  # lazy — создадим при первом вызове.

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    async def invoke(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        system_prompt: str | None = None,
    ) -> LLMResponse:
        client = self._get_client()
        oai_messages = _messages_to_openai(messages, system_prompt)
        oai_tools = _tools_to_openai(tools)

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": oai_messages,
        }
        if oai_tools:
            kwargs["tools"] = oai_tools

        try:
            response = client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 — оборачиваем всё SDK-шное.
            raise LLMTransportError(
                f"OpenAIProvider.invoke: ошибка SDK/сети: {exc}"
            ) from exc

        return _response_to_llm(response, fallback_model=self.model)

    async def stream(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        system_prompt: str | None = None,
    ) -> AsyncIterator[LLMChunk]:
        client = self._get_client()
        oai_messages = _messages_to_openai(messages, system_prompt)
        oai_tools = _tools_to_openai(tools)

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": oai_messages,
            "stream": True,
        }
        if oai_tools:
            kwargs["tools"] = oai_tools

        try:
            stream = client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001
            raise LLMTransportError(
                f"OpenAIProvider.stream: ошибка SDK/сети: {exc}"
            ) from exc

        # Аккумулируем tool_calls по индексу (OpenAI шлёт delta-ы).
        # tool_buffers[index] = {"id": str, "name": str, "args": str}
        tool_buffers: dict[int, dict[str, str]] = {}
        # Какие tool_use_start мы уже отправили (по index).
        started: set[int] = set()
        final_finish: str | None = None
        usage_dict: dict[str, int] | None = None
        model_name = self.model

        try:
            for chunk in stream:
                # chunk — ChatCompletionChunk
                if getattr(chunk, "model", None):
                    model_name = chunk.model
                choices = getattr(chunk, "choices", None) or []
                for choice in choices:
                    delta = getattr(choice, "delta", None)
                    if delta is None:
                        continue
                    text_part = getattr(delta, "content", None)
                    if text_part:
                        yield TextDelta(text=text_part)
                    raw_tool_calls = getattr(delta, "tool_calls", None) or []
                    for tc in raw_tool_calls:
                        idx = getattr(tc, "index", 0) or 0
                        buf = tool_buffers.setdefault(
                            idx, {"id": "", "name": "", "args": ""}
                        )
                        tc_id = getattr(tc, "id", None)
                        if tc_id:
                            buf["id"] = tc_id
                        func = getattr(tc, "function", None)
                        if func is not None:
                            name = getattr(func, "name", None)
                            if name:
                                buf["name"] = name
                            args = getattr(func, "arguments", None)
                            if args:
                                buf["args"] += args
                        # Как только узнали id и name — стартуем блок.
                        if buf["id"] and buf["name"] and idx not in started:
                            started.add(idx)
                            yield ToolUseStart(id=buf["id"], name=buf["name"])
                        if started and idx in started and func is not None:
                            args = getattr(func, "arguments", None)
                            if args:
                                yield ToolUseDelta(
                                    id=buf["id"], partial_json=args
                                )
                    finish = getattr(choice, "finish_reason", None)
                    if finish:
                        final_finish = finish

                # На последнем чанке OpenAI может приложить usage.
                usage = getattr(chunk, "usage", None)
                if usage is not None:
                    usage_dict = {
                        "input_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                        "output_tokens": getattr(
                            usage, "completion_tokens", 0
                        )
                        or 0,
                    }
        except LLMTransportError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise LLMTransportError(
                f"OpenAIProvider.stream: сбой при чтении стрима: {exc}"
            ) from exc

        # Закрываем tool_use-блоки.
        for idx in sorted(started):
            buf = tool_buffers[idx]
            try:
                parsed = json.loads(buf["args"]) if buf["args"] else {}
            except json.JSONDecodeError:
                # Пусть наверху разбираются — но сам стрим не валим.
                parsed = {"__raw": buf["args"]}
            yield ToolUseEnd(id=buf["id"], input=parsed)

        stop_reason = _map_finish_reason(final_finish)
        usage_obj = Usage(
            input_tokens=(usage_dict or {}).get("input_tokens", 0),
            output_tokens=(usage_dict or {}).get("output_tokens", 0),
        )
        yield MessageStop(
            stop_reason=stop_reason,
            usage=usage_obj,
            model=model_name,
        )

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI  # lazy
        except ImportError as exc:  # pragma: no cover — зависит от окружения.
            raise LLMConfigError(
                "OpenAIProvider: пакет `openai` не установлен. "
                "Добавьте `openai>=1.0.0` в requirements."
            ) from exc

        kwargs: dict[str, Any] = {"api_key": self._api_key}
        if self._base_url:
            kwargs["base_url"] = self._base_url
        try:
            self._client = OpenAI(**kwargs)
        except Exception as exc:  # noqa: BLE001
            raise LLMConfigError(
                f"OpenAIProvider: не удалось создать OpenAI-клиент: {exc}"
            ) from exc
        return self._client


# ---------------------------------------------------------------------------
# Mapping helpers (Anthropic-style ↔ OpenAI chat completions)
# ---------------------------------------------------------------------------


def _messages_to_openai(
    messages: list[Message],
    system_prompt: str | None,
) -> list[dict[str, Any]]:
    """Сконвертировать наши `Message` в формат OpenAI chat-completions.

    Правила (ADR-001 §2.2):
      * `system_prompt`, если задан, идёт первым сообщением `{role:"system"}`.
      * `user` с одним `TextBlock` (или строкой) → `{role:"user", content:str}`.
      * `assistant` с `TextBlock`+`ToolUseBlock` → `{role:"assistant",
        content:str|None, tool_calls:[{id,type:function,function:{name,
        arguments}}]}`.
      * `user` с `ToolResultBlock`'ами → распаковывается в N отдельных
        сообщений `{role:"tool", tool_call_id, content}` (OpenAI хранит
        результат каждого tool отдельным сообщением, в отличие от Anthropic).
    """
    out: list[dict[str, Any]] = []
    if system_prompt:
        out.append({"role": "system", "content": system_prompt})

    for msg in messages:
        blocks = _normalize_content(msg.content)

        # Каждый Message может «раскрыться» в несколько OpenAI-сообщений
        # (если внутри несколько tool_result-блоков).
        tool_results = [b for b in blocks if isinstance(b, ToolResultBlock)]
        non_tool_results = [
            b for b in blocks if not isinstance(b, ToolResultBlock)
        ]

        if msg.role == "user":
            # tool_result-блоки превращаются в отдельные tool-сообщения.
            for tr in tool_results:
                out.append(_tool_result_to_openai(tr))

            if non_tool_results:
                text_chunks = [
                    b.text for b in non_tool_results if isinstance(b, TextBlock)
                ]
                if text_chunks:
                    out.append(
                        {
                            "role": "user",
                            "content": "\n".join(text_chunks),
                        }
                    )
            continue

        # role == "assistant"
        text_chunks = [
            b.text for b in non_tool_results if isinstance(b, TextBlock)
        ]
        tool_uses = [
            b for b in non_tool_results if isinstance(b, ToolUseBlock)
        ]

        oai_msg: dict[str, Any] = {"role": "assistant"}
        content_str = "\n".join(text_chunks) if text_chunks else None
        # OpenAI: при наличии tool_calls content может быть None.
        oai_msg["content"] = content_str
        if tool_uses:
            oai_msg["tool_calls"] = [
                {
                    "id": tu.id,
                    "type": "function",
                    "function": {
                        "name": tu.name,
                        "arguments": json.dumps(tu.input, ensure_ascii=False),
                    },
                }
                for tu in tool_uses
            ]
        out.append(oai_msg)

    return out


def _tool_result_to_openai(block: ToolResultBlock) -> dict[str, Any]:
    """`ToolResultBlock` → OpenAI `{role:"tool", tool_call_id, content}`."""
    if isinstance(block.content, str):
        content = block.content
    else:
        # Список TextBlock'ов — склеиваем.
        content = "\n".join(
            b.text for b in block.content if isinstance(b, TextBlock)
        )
    if block.is_error:
        # Сигнализируем модели префиксом — OpenAI не имеет отдельного флага.
        content = f"[ERROR] {content}"
    return {
        "role": "tool",
        "tool_call_id": block.tool_use_id,
        "content": content,
    }


def _normalize_content(
    content: str | list[ContentBlock],
) -> list[ContentBlock]:
    """`str` → `[TextBlock(str)]`; список оставляем как есть."""
    if isinstance(content, str):
        return [TextBlock(text=content)]
    return list(content)


def _tools_to_openai(tools: list[Tool] | None) -> list[dict[str, Any]]:
    """`Tool` → OpenAI tool-schema (`{type:function, function:{...}}`)."""
    if not tools:
        return []
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            },
        }
        for t in tools
    ]


def _response_to_llm(response: Any, *, fallback_model: str) -> LLMResponse:
    """Развернуть `ChatCompletion` обратно в `LLMResponse`."""
    choices = getattr(response, "choices", None) or []
    if not choices:
        raise LLMTransportError(
            "OpenAIProvider: ответ не содержит ни одного choice."
        )
    choice = choices[0]
    message = getattr(choice, "message", None)
    if message is None:
        raise LLMTransportError(
            "OpenAIProvider: choice без поля message."
        )

    blocks: list[ContentBlock] = []
    text = getattr(message, "content", None)
    if text:
        blocks.append(TextBlock(text=text))

    raw_tool_calls = getattr(message, "tool_calls", None) or []
    for tc in raw_tool_calls:
        tc_id = getattr(tc, "id", "") or ""
        func = getattr(tc, "function", None)
        name = getattr(func, "name", "") if func is not None else ""
        args_raw = getattr(func, "arguments", "") if func is not None else ""
        try:
            args = json.loads(args_raw) if args_raw else {}
        except json.JSONDecodeError:
            # Сохраним сырой текст, чтобы вызывающий мог разобраться.
            args = {"__raw": args_raw}
        blocks.append(ToolUseBlock(id=tc_id, name=name, input=args))

    stop_reason = _map_finish_reason(getattr(choice, "finish_reason", None))

    usage_attr = getattr(response, "usage", None)
    usage = Usage(
        input_tokens=getattr(usage_attr, "prompt_tokens", 0) or 0,
        output_tokens=getattr(usage_attr, "completion_tokens", 0) or 0,
    )

    model_name = getattr(response, "model", None) or fallback_model

    raw_dict: dict | None
    try:
        # У pydantic-моделей openai SDK есть model_dump.
        raw_dict = response.model_dump()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        raw_dict = None

    return LLMResponse(
        content=blocks,
        stop_reason=stop_reason,
        usage=usage,
        model=model_name,
        raw=raw_dict,
    )


def _map_finish_reason(finish: str | None) -> StopReason:
    """OpenAI `finish_reason` → наш `StopReason`. По умолчанию — `end_turn`."""
    if finish is None:
        return "end_turn"
    return _FINISH_REASON_MAP.get(finish, "end_turn")


__all__ = ["OpenAIProvider"]

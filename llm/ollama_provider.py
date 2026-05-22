"""`OllamaProvider` — реализация `LLMProvider` поверх Ollama REST API.

ADR-001 §2.3 / §6.1 («Ollama JSON-prompting»). Этот провайдер:

* Принимает Anthropic-style content-blocks (`TextBlock`, `ToolUseBlock`,
  `ToolResultBlock`) и переводит их в Ollama `/api/chat` формат
  (роли `user`/`assistant`/`system`, плоский текст).
* Tool-calling реализован через JSON-prompting: если переданы `tools`,
  добавляем к system-prompt инструкцию с описаниями инструментов и просим
  модель отвечать строго JSON-объектом `{"tool": "name", "args": {...}}`
  при необходимости вызвать инструмент. При невалидном JSON — fallback:
  возвращаем как обычный TextBlock (не падаем).
* `invoke`: POST `/api/chat` с `"stream": false` → возвращает `LLMResponse`.
* `stream`: POST `/api/chat` с `"stream": true` → читает NDJSON построчно,
  возвращает async-генератор `LLMChunk`'ов.
* Любую сетевую ошибку (httpx) оборачивает в `LLMTransportError`.
* `Usage` всегда содержит нули (Ollama не поддерживает кэширование;
  токены доступны только в финальном чанке `/api/chat` stream).
"""

from __future__ import annotations

import json
import uuid
from typing import AsyncIterator

import httpx

from .base import (
    ContentBlock,
    LLMChunk,
    LLMProvider,
    LLMResponse,
    LLMTransportError,
    Message,
    MessageStop,
    TextBlock,
    TextDelta,
    Tool,
    ToolResultBlock,
    ToolUseBlock,
    ToolUseEnd,
    ToolUseStart,
    Usage,
)

# ---------------------------------------------------------------------------
# System-prompt template для JSON-tool-calling
# ---------------------------------------------------------------------------

_TOOL_SYSTEM_TEMPLATE = """\
You have access to the following tools:
{tool_list}

When you need to call a tool, respond ONLY with JSON (no extra text):
{{"tool": "<tool_name>", "args": {{...}}}}

If no tool call is needed, respond normally as plain text.\
"""


class OllamaProvider(LLMProvider):
    """LLMProvider поверх Ollama `/api/chat` REST API.

    Args:
        model: имя модели, зарегистрированной в Ollama (например `llama3.1`,
            `mistral`, `qwen2`).
        base_url: базовый URL Ollama-сервера. По умолчанию
            `http://localhost:11434`.
        timeout: таймаут HTTP-запроса в секундах (по умолчанию 120).

    Raises:
        LLMTransportError: любая сетевая ошибка при вызове Ollama.
    """

    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434",
        *,
        timeout: float = 120.0,
    ) -> None:
        self.model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    async def invoke(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        system_prompt: str | None = None,
    ) -> LLMResponse:
        """Один цикл запрос/ответ через Ollama `/api/chat`."""
        effective_system = _build_system(system_prompt, tools)
        ollama_messages = _messages_to_ollama(messages, effective_system)

        body = {
            "model": self.model,
            "messages": ollama_messages,
            "stream": False,
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/api/chat",
                    json=body,
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise LLMTransportError(
                f"OllamaProvider.invoke: HTTP-ошибка: {exc}"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise LLMTransportError(
                f"OllamaProvider.invoke: ошибка запроса: {exc}"
            ) from exc

        return _response_to_llm(data, model=self.model, tools=tools)

    async def stream(  # type: ignore[override]
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        system_prompt: str | None = None,
    ) -> AsyncIterator[LLMChunk]:
        """Стриминговый вариант через Ollama `/api/chat` с `stream: true`.

        Ollama пишет один JSON-объект на строку (NDJSON). Последний объект
        содержит `"done": true` и финальную статистику.
        При JSON-prompting инструменты не передаются стримом дельтами —
        весь ответ накапливается и разбирается в конце.
        """
        effective_system = _build_system(system_prompt, tools)
        ollama_messages = _messages_to_ollama(messages, effective_system)

        body = {
            "model": self.model,
            "messages": ollama_messages,
            "stream": True,
        }

        accumulated_text = ""
        prompt_tokens = 0
        completion_tokens = 0
        model_name = self.model

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self._base_url}/api/chat",
                    json=body,
                ) as resp:
                    resp.raise_for_status()
                    async for raw_line in resp.aiter_lines():
                        raw_line = raw_line.strip()
                        if not raw_line:
                            continue
                        try:
                            chunk = json.loads(raw_line)
                        except json.JSONDecodeError:
                            continue

                        # Читаем model из первого чанка.
                        if chunk.get("model"):
                            model_name = chunk["model"]

                        # Дельта текста.
                        msg = chunk.get("message") or {}
                        delta_text = msg.get("content") or ""
                        if delta_text:
                            accumulated_text += delta_text

                        # Финальный чанк.
                        if chunk.get("done"):
                            prompt_tokens = chunk.get("prompt_eval_count", 0) or 0
                            completion_tokens = (
                                chunk.get("eval_count", 0) or 0
                            )
                            break

        except LLMTransportError:
            raise
        except httpx.HTTPError as exc:
            raise LLMTransportError(
                f"OllamaProvider.stream: HTTP-ошибка: {exc}"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise LLMTransportError(
                f"OllamaProvider.stream: ошибка при чтении стрима: {exc}"
            ) from exc

        # Разбираем накопленный текст на предмет tool-call JSON.
        if tools and accumulated_text.strip():
            tool_block = _try_parse_tool_call(accumulated_text)
            if tool_block is not None:
                yield ToolUseStart(id=tool_block.id, name=tool_block.name)
                args_json = json.dumps(tool_block.input, ensure_ascii=False)
                yield ToolUseEnd(id=tool_block.id, input=tool_block.input)
                usage = Usage(
                    input_tokens=prompt_tokens,
                    output_tokens=completion_tokens,
                )
                yield MessageStop(
                    stop_reason="tool_use",
                    usage=usage,
                    model=model_name,
                )
                return

        # Обычный текстовый ответ: эмитируем весь накопленный текст одним дельта.
        if accumulated_text:
            yield TextDelta(text=accumulated_text)

        usage = Usage(
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
        )
        yield MessageStop(
            stop_reason="end_turn",
            usage=usage,
            model=model_name,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_system(
    system_prompt: str | None,
    tools: list[Tool] | None,
) -> str | None:
    """Собрать эффективный system-prompt: исходный + tool-инструкция."""
    if not tools:
        return system_prompt

    tool_descriptions = []
    for t in tools:
        schema_str = json.dumps(t.input_schema, ensure_ascii=False)
        tool_descriptions.append(
            f"- {t.name}: {t.description}\n  args schema: {schema_str}"
        )
    tool_list = "\n".join(tool_descriptions)
    tool_instruction = _TOOL_SYSTEM_TEMPLATE.format(tool_list=tool_list)

    if system_prompt:
        return f"{system_prompt}\n\n{tool_instruction}"
    return tool_instruction


def _messages_to_ollama(
    messages: list[Message],
    system_prompt: str | None,
) -> list[dict]:
    """Конвертировать `Message` в Ollama-формат (роли user/assistant/system).

    Правила:
      * `system_prompt` идёт первым сообщением `{role: "system"}`.
      * `TextBlock` → склеиваются в строку.
      * `ToolUseBlock` в assistant → сериализуется в JSON-строку (для истории).
      * `ToolResultBlock` в user → добавляется как user-сообщение с текстом.
    """
    out: list[dict] = []
    if system_prompt:
        out.append({"role": "system", "content": system_prompt})

    for msg in messages:
        blocks: list[ContentBlock]
        if isinstance(msg.content, str):
            blocks = [TextBlock(text=msg.content)]
        else:
            blocks = list(msg.content)

        parts: list[str] = []
        for block in blocks:
            if isinstance(block, TextBlock):
                parts.append(block.text)
            elif isinstance(block, ToolUseBlock):
                # Сериализуем tool_use обратно в JSON (для истории диалога).
                parts.append(
                    json.dumps(
                        {"tool": block.name, "args": block.input},
                        ensure_ascii=False,
                    )
                )
            elif isinstance(block, ToolResultBlock):
                # tool_result попадает в user-сообщение как plain text.
                if isinstance(block.content, str):
                    result_text = block.content
                else:
                    result_text = "\n".join(
                        b.text
                        for b in block.content
                        if isinstance(b, TextBlock)
                    )
                if block.is_error:
                    result_text = f"[ERROR] {result_text}"
                parts.append(f"[tool_result for {block.tool_use_id}]: {result_text}")

        content = "\n".join(parts)
        out.append({"role": msg.role, "content": content})

    return out


def _try_parse_tool_call(text: str) -> ToolUseBlock | None:
    """Попытаться распарсить JSON tool-call из ответа модели.

    Возвращает `ToolUseBlock` если распознан, иначе `None` (fallback).
    Ищет JSON-объект с ключами `"tool"` и `"args"` в тексте ответа
    (модель иногда добавляет текст до/после JSON).
    """
    text = text.strip()
    # Сначала пробуем весь текст как JSON.
    candidates = [text]

    # Попытка извлечь JSON-блок из текста (между первой `{` и последней `}`).
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(text[start : end + 1])

    for candidate in candidates:
        try:
            obj = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict) and "tool" in obj and "args" in obj:
            tool_id = f"toolu_{uuid.uuid4().hex[:12]}"
            args = obj["args"] if isinstance(obj["args"], dict) else {}
            return ToolUseBlock(id=tool_id, name=str(obj["tool"]), input=args)

    return None


def _response_to_llm(
    data: dict,
    *,
    model: str,
    tools: list[Tool] | None,
) -> LLMResponse:
    """Развернуть ответ Ollama `/api/chat` в `LLMResponse`.

    При наличии `tools` пытаемся разобрать JSON tool-call в тексте ответа.
    Если парсинг не удался — возвращаем как `TextBlock` (fallback).
    """
    msg = data.get("message") or {}
    raw_text: str = msg.get("content") or ""
    model_name: str = data.get("model") or model

    # Usage (Ollama пишет токены в финальный ответ при stream=false).
    prompt_tokens = data.get("prompt_eval_count", 0) or 0
    completion_tokens = data.get("eval_count", 0) or 0
    usage = Usage(
        input_tokens=prompt_tokens,
        output_tokens=completion_tokens,
    )

    # Попытка распарсить tool-call.
    if tools and raw_text.strip():
        tool_block = _try_parse_tool_call(raw_text)
        if tool_block is not None:
            return LLMResponse(
                content=[tool_block],
                stop_reason="tool_use",
                usage=usage,
                model=model_name,
                raw=data,
            )

    # Обычный текстовый ответ.
    blocks: list[ContentBlock] = []
    if raw_text:
        blocks.append(TextBlock(text=raw_text))

    return LLMResponse(
        content=blocks,
        stop_reason="end_turn",
        usage=usage,
        model=model_name,
        raw=data,
    )


__all__ = ["OllamaProvider"]

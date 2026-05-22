"""`ClaudeCLIProvider` — обёртка над `claude` CLI (ADR-001 §2.5, E6.3).

Реализует `LLMProvider` через subprocess-вызов `claude -p ...` (см. как
это делает `commands/devboard-work.sh`). Это самый дешёвый путь к
Anthropic Claude без зависимости от `anthropic` SDK — все аутентификации
и rate-limit'ы решает уже сама CLI-утилита.

Отдельный `ClaudeSDKProvider` (через `anthropic` Python SDK) — это
бонус-задача, оставлен заглушкой в `llm/claude_sdk_provider.py`.

Формат вывода CLI:

* `--output-format=text` (default) — обычный текст в stdout. Используется
  в `invoke()`.
* `--output-format=stream-json --include-partial-messages` — NDJSON-поток
  событий, тот же что парсит дашборд. Используется в `stream()`.

Это headless-режим: интерактивный диалог, MCP-инструменты, system-prompt
передаются через CLI-флаги. Конструктор принимает:

* `model` — alias модели (`claude-opus-4-7`, `sonnet`, `haiku`, ...).
* `allowed_tools` — список разрешённых инструментов (для
  `--allowed-tools`). Если `None` — флаг не передаётся (claude применит
  свой дефолт).
* `mcp_config` — путь к `.mcp.json` (для `--mcp-config`). Опционально.
* `permission_mode` — `bypassPermissions` / `default` / `acceptEdits`.
  В headless-режиме devboard нужен `bypassPermissions` (approval-gates
  реализованы на уровне role-промтов).
* `extra_args` — дополнительные CLI-флаги, на всякий случай.
* `cli_path` — путь к бинарю `claude`. По умолчанию ищется в PATH.

Ошибки:

* `LLMTransportError` — `claude` не найден в PATH, или процесс упал с
  ненулевым кодом, или stdout невалидный JSON в stream-режиме.
* `LLMConfigError` — конструктор получил мусор (пустая модель и т.п.).
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import AsyncIterator, Iterable, Optional

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


# По умолчанию dashboard/work.sh использует именно `claude-opus-4-7`.
_DEFAULT_MODEL = "claude-opus-4-7"


@dataclass
class ClaudeCLIProvider(LLMProvider):
    """`LLMProvider`, поверх бинаря `claude` (Claude Code CLI).

    Не делает прямых HTTP-вызовов к Anthropic — это работа CLI. Зато
    унаследует все её фичи: MCP, allowed-tools, prompt-cache, и т.п.
    Парсит NDJSON stream-json формат (`--output-format=stream-json
    --include-partial-messages`) в общий `LLMChunk`-тип.
    """

    model: str = _DEFAULT_MODEL
    allowed_tools: Optional[list[str]] = None
    mcp_config: Optional[str] = None
    permission_mode: str = "bypassPermissions"
    cli_path: str = "claude"
    extra_args: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.model, str) or not self.model.strip():
            raise LLMConfigError(
                "ClaudeCLIProvider: 'model' должен быть непустой строкой."
            )
        self.model = self.model.strip()
        if self.allowed_tools is not None and not isinstance(
            self.allowed_tools, list
        ):
            raise LLMConfigError(
                "ClaudeCLIProvider: 'allowed_tools' должен быть list или None."
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def invoke(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        system_prompt: str | None = None,
    ) -> LLMResponse:
        """Однократный non-streaming вызов claude CLI.

        В headless-режиме CLI не поддерживает многоходовых диалогов из
        коробки — поэтому `messages` склеиваются в один плоский prompt.
        Это компромисс задокументирован в ADR-001 (см. риск
        «CLI ≠ полноценный диалог»). Для штатных devboard сценариев
        (одношаговый запуск тимлида/бэкенда) этого достаточно.

        `tools` здесь — описание схем для модели. CLI принимает только
        список *имён* через `--allowed-tools` (схемы он уже знает от MCP).
        Поэтому если `tools` передан, мы извлекаем из него имена и
        мерджим с `self.allowed_tools`.
        """

        prompt = _build_prompt(messages)
        cmd = self._build_cmd(
            prompt=prompt,
            system_prompt=system_prompt,
            tools=tools,
            stream=False,
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise LLMTransportError(
                f"claude CLI not found in PATH (cli_path={self.cli_path!r})"
            ) from exc

        stdout_b, stderr_b = await proc.communicate()
        stdout = (stdout_b or b"").decode("utf-8", errors="replace")
        stderr = (stderr_b or b"").decode("utf-8", errors="replace")

        if proc.returncode != 0:
            raise LLMTransportError(
                f"claude CLI exited with code {proc.returncode}: "
                f"{stderr.strip() or stdout.strip()[:200]}"
            )

        text = stdout.strip()
        return LLMResponse(
            content=[TextBlock(text=text)],
            stop_reason="end_turn",
            usage=Usage(),
            model=self.model,
            raw={"stdout": stdout, "stderr": stderr},
        )

    async def stream(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        system_prompt: str | None = None,
    ) -> AsyncIterator[LLMChunk]:
        """Стриминговый вариант: `--output-format=stream-json`.

        Парсит NDJSON (по одному JSON-объекту на строку) в общие
        `LLMChunk`-типы:

        * `assistant`-событие с `text`-блоком → `TextDelta`
        * `assistant`-событие с `tool_use`-блоком → `ToolUseStart`
          + `ToolUseDelta` (полный JSON одним куском) + `ToolUseEnd`
        * `result`-событие → финальный `MessageStop` с usage из события

        Если CLI выплюнул мусор — `LLMTransportError`.
        """

        prompt = _build_prompt(messages)
        cmd = self._build_cmd(
            prompt=prompt,
            system_prompt=system_prompt,
            tools=tools,
            stream=True,
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise LLMTransportError(
                f"claude CLI not found in PATH (cli_path={self.cli_path!r})"
            ) from exc

        assert proc.stdout is not None
        stop_reason: StopReason = "end_turn"
        final_usage = Usage()
        saw_message_stop = False

        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            raw = line.decode("utf-8", errors="replace").strip()
            if not raw:
                continue
            try:
                ev = json.loads(raw)
            except json.JSONDecodeError as exc:
                # Прерываем — но даём процессу шанс закончиться.
                await proc.wait()
                raise LLMTransportError(
                    f"claude CLI stream-json: невалидный JSON в строке: "
                    f"{raw[:120]!r}"
                ) from exc

            for chunk in _events_to_chunks(ev, self.model):
                if isinstance(chunk, MessageStop):
                    stop_reason = chunk.stop_reason
                    final_usage = chunk.usage
                    saw_message_stop = True
                yield chunk

        rc = await proc.wait()
        if rc != 0:
            stderr_b = await proc.stderr.read() if proc.stderr else b""
            stderr = stderr_b.decode("utf-8", errors="replace")
            raise LLMTransportError(
                f"claude CLI exited with code {rc}: {stderr.strip()[:200]}"
            )

        if not saw_message_stop:
            # Подстраховка: если CLI не прислал явного финала, всё равно
            # отдадим один MessageStop, чтобы консьюмеру не пришлось
            # обрабатывать «вечный» поток.
            yield MessageStop(
                stop_reason=stop_reason,
                usage=final_usage,
                model=self.model,
            )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_cmd(
        self,
        prompt: str,
        system_prompt: str | None,
        tools: list[Tool] | None,
        stream: bool,
    ) -> list[str]:
        """Собрать argv для claude CLI."""
        cmd: list[str] = [
            self.cli_path,
            "--model",
            self.model,
            "--permission-mode",
            self.permission_mode,
        ]
        if system_prompt:
            cmd.extend(["--append-system-prompt", system_prompt])
        if self.mcp_config:
            cmd.extend(["--mcp-config", self.mcp_config])

        allowed = list(self.allowed_tools or [])
        if tools:
            # CLI принимает имена, не полные схемы.
            allowed.extend(t.name for t in tools if t.name)
        if allowed:
            # CLI ожидает имена через запятую — это документировано в
            # `claude --help`.
            cmd.extend(["--allowed-tools", ",".join(allowed)])

        if stream:
            cmd.extend(
                [
                    "--output-format",
                    "stream-json",
                    "--verbose",
                    "--include-partial-messages",
                ]
            )

        cmd.extend(self.extra_args)
        cmd.extend(["--print", prompt])
        return cmd


# ---------------------------------------------------------------------------
# Helpers (module-level, чтобы их можно было юнит-тестировать без процесса)
# ---------------------------------------------------------------------------


def _build_prompt(messages: list[Message]) -> str:
    """Слить список Message в один плоский prompt для `--print`.

    Формат:
        <USER>
        ...текст пользователя...
        </USER>
        <ASSISTANT>
        ...текст модели...
        </ASSISTANT>
        ...
        <USER>
        последнее сообщение пользователя
        </USER>

    Если на входе ровно одно user-сообщение со строковым контентом —
    отдаём его как есть, без тэгов (типовой однопроходный сценарий).
    """
    if not messages:
        return ""
    if (
        len(messages) == 1
        and messages[0].role == "user"
        and isinstance(messages[0].content, str)
    ):
        return messages[0].content

    parts: list[str] = []
    for msg in messages:
        tag = msg.role.upper()
        body = _render_content(msg.content)
        parts.append(f"<{tag}>\n{body}\n</{tag}>")
    return "\n".join(parts)


def _render_content(content) -> str:
    """Превратить content (str | list[ContentBlock]) в плоский текст."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)
    out: list[str] = []
    for block in content:
        if isinstance(block, TextBlock):
            out.append(block.text)
        elif isinstance(block, ToolUseBlock):
            out.append(
                f"[tool_use {block.name} id={block.id} input="
                f"{json.dumps(block.input, ensure_ascii=False)}]"
            )
        elif isinstance(block, ToolResultBlock):
            inner: str
            if isinstance(block.content, str):
                inner = block.content
            else:
                inner = "\n".join(
                    b.text for b in block.content if isinstance(b, TextBlock)
                )
            prefix = "tool_error" if block.is_error else "tool_result"
            out.append(f"[{prefix} id={block.tool_use_id}] {inner}")
        else:
            out.append(str(block))
    return "\n".join(out)


def _events_to_chunks(ev: dict, default_model: str) -> Iterable[LLMChunk]:
    """Перевести одно событие claude stream-json в 0+ LLMChunk."""

    et = ev.get("type")

    if et == "assistant":
        msg = ev.get("message") or {}
        for block in msg.get("content", []) or []:
            btype = block.get("type")
            if btype == "text":
                txt = block.get("text") or ""
                if txt:
                    yield TextDelta(text=txt)
            elif btype == "tool_use":
                tid = block.get("id") or ""
                name = block.get("name") or ""
                inp = block.get("input") or {}
                yield ToolUseStart(id=tid, name=name)
                # Полные input'ы кладём одним куском — claude CLI уже отдаёт
                # их собранными, потоковая сборка JSON-фрагментов нам не
                # нужна (это особенность low-level Anthropic API).
                yield ToolUseDelta(
                    id=tid,
                    partial_json=json.dumps(inp, ensure_ascii=False),
                )
                yield ToolUseEnd(id=tid, input=inp)
        return

    if et == "result":
        usage_raw = ev.get("usage") or {}
        usage = Usage(
            input_tokens=int(usage_raw.get("input_tokens") or 0),
            output_tokens=int(usage_raw.get("output_tokens") or 0),
            cache_creation_input_tokens=int(
                usage_raw.get("cache_creation_input_tokens") or 0
            ),
            cache_read_input_tokens=int(
                usage_raw.get("cache_read_input_tokens") or 0
            ),
        )
        stop_reason = _normalize_stop_reason(
            ev.get("stop_reason") or ev.get("subtype")
        )
        model = ev.get("model") or default_model
        if not ev.get("model"):
            # Stream-json у claude-code 2.x кладёт фактическую модель в
            # `modelUsage` (см. dashboard/app.py).
            mu = ev.get("modelUsage") or {}
            if isinstance(mu, dict) and mu:
                model = max(
                    mu.keys(),
                    key=lambda k: (mu[k] or {}).get("costUSD") or 0,
                )
        yield MessageStop(
            stop_reason=stop_reason,
            usage=usage,
            model=model,
        )
        return

    # system/init, user (tool_result), stream_event — игнорируем.


_VALID_STOP_REASONS = {"end_turn", "tool_use", "max_tokens", "stop_sequence"}


def _normalize_stop_reason(raw) -> StopReason:
    """Не-стандартные значения из CLI приводим к ближайшему валидному."""
    if isinstance(raw, str) and raw in _VALID_STOP_REASONS:
        return raw  # type: ignore[return-value]
    # `subtype == "success"` и т.п. — трактуем как обычное завершение.
    return "end_turn"


__all__ = [
    "ClaudeCLIProvider",
]

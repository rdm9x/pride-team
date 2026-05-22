# ADR-001 — Интерфейс `LLMProvider`

- **Status:** Accepted (2026-05-21)
- **Date:** 2026-05-21
- **Authors:** архитектор (pride-team)
- **Epic:** E6 — Multi-LLM (parent task `af976e279b39`)
- **Supersedes:** —

## 1. Context

Сейчас pride-team хардкодит вызов Claude:

```
exec claude --append-system-prompt "$PROMPT" \
            --permission-mode bypassPermissions \
            --model "$MODEL_ALIAS" \
            --mcp-config "$REPO_ROOT/.mcp.json" \
            --output-format stream-json ...
```

(см. `команды/pride-team-work.sh`, `дашборд/app.py::_format_stream_event`).

Это блокирует две группы пользователей:

1. У кого есть **OpenAI API key**, но нет подписки Anthropic / установленного `claude` CLI.
2. Кто хочет гонять команду **локально на Ollama** (приватность, нулевая стоимость, оффлайн).

Цель эпика E6 — заменить хардкод на абстракцию `LLMProvider`, через которую любая роль (`роли/*.md`) может выбрать движок одной строкой во frontmatter (`llm: claude|openai|ollama`).

Сейчас в кодовой базе нет ни папки `llm/`, ни SDK-зависимостей (`anthropic`/`openai`/`httpx`-клиента к Ollama). Stream-формат claude CLI уже частично распарсен в дашборде — это ориентир для контракта `LLMChunk`.

## 2. Decision

### 2.1. Контракт

Вводим **`LLMProvider`** как `abc.ABC` с двумя async-методами:

```python
class LLMProvider(ABC):
    """Единый интерфейс к LLM. Реализации: Claude (CLI/SDK), OpenAI, Ollama."""

    @abstractmethod
    async def invoke(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        system_prompt: str | None = None,
    ) -> LLMResponse:
        """Один цикл запрос/ответ. Возвращает финальный ответ модели.

        Если модель вернула tool_use-блоки — они в response.content;
        вызов и tool_result-фидбэк управляются вызывающим (агент-loop),
        не самим провайдером. Это позволяет переиспользовать одного
        провайдера для нескольких ролей и сохранять разделение
        ответственностей.
        """

    @abstractmethod
    async def stream(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        system_prompt: str | None = None,
    ) -> AsyncIterator[LLMChunk]:
        """Стриминговый вариант. Yields инкрементальные чанки.

        Чанк — один из: TextDelta | ToolUseStart | ToolUseDelta |
        ToolUseEnd | MessageStop. Дашборд подписывается на это в SSE.
        """
```

### 2.2. Формат сообщений: **Anthropic-style** (с маппингом для остальных)

`Message` — dataclass:

```python
@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant"]   # system — отдельный аргумент
    content: str | list[ContentBlock]    # str → один TextBlock

ContentBlock = TextBlock | ToolUseBlock | ToolResultBlock
```

Содержимое (`ContentBlock`) поддерживает три типа:

- `TextBlock(text: str)`
- `ToolUseBlock(id: str, name: str, input: dict)`
- `ToolResultBlock(tool_use_id: str, content: str | list[TextBlock], is_error: bool = False)`

**Почему Anthropic-формат, а не OpenAI:**

| Критерий | Anthropic-style | OpenAI-style |
|---|---|---|
| `system` | отдельный параметр | роль в `messages` |
| Tool-результаты | блок внутри `user` | отдельная роль `tool` |
| Multi-block content | нативно (text + tool_use в одном assistant-сообщении) | через `tool_calls` поле сбоку |
| Reasoning blocks (extended thinking) | нативно | нет |
| Multimodal | блок `image` | блок `image_url` (схожий) |

Anthropic-схема **строго мощнее**: tool_use и текст уживаются в одном assistant-сообщении, что критично для multi-step агента. Конвертация Anthropic → OpenAI — детерминированная (разнести tool_use в `tool_calls`, превратить ToolResult в `role=tool`). Обратное направление лossy (нельзя одновременно держать текст + tool_call в OpenAI-ответе без хака). Дополнительно — текущий код в `дашборд/app.py` уже парсит claude stream-json в терминах `text` / `tool_use` / `tool_result`, так что cost миграции = 0.

### 2.3. Tools — JSON Schema (Anthropic-форма)

```python
@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict      # JSON Schema (draft 2020-12)
```

OpenAI требует обёртку `{"type": "function", "function": {...}}` — это делает `OpenAIProvider.invoke` при сериализации. Ollama (без native tool-calls) получает инструменты через инжектированный системный промт с JSON-протоколом (см. E6.5).

MCP-инструменты pride-tasks **остаются вне** `LLMProvider`. MCP-сервер живёт через `.mcp.json` и подключается на уровне `ClaudeCLIProvider` (передачей `--mcp-config`). Для `OpenAIProvider`/`OllamaProvider` MCP-tools будут конвертироваться в обычные `Tool`-объявления через MCP-клиент (отдельный слой `mcp_bridge` — задача E6.4/E6.5).

### 2.4. Ответ и чанки

```python
@dataclass(frozen=True)
class LLMResponse:
    content: list[ContentBlock]          # text + tool_use вперемешку
    stop_reason: Literal["end_turn", "tool_use", "max_tokens", "stop_sequence"]
    usage: Usage                         # input_tokens, output_tokens, cache_*
    model: str                           # фактическая модель, которая ответила
    raw: dict | None = None              # сырой ответ провайдера (для отладки/логов)

LLMChunk = TextDelta | ToolUseStart | ToolUseDelta | ToolUseEnd | MessageStop
```

`Usage.cache_*` есть у Anthropic и (с недавнего времени) у OpenAI, у Ollama — нули.

### 2.5. Конфигурация и фабрика

```python
def create_provider(config: dict) -> LLMProvider:
    """config — фрагмент frontmatter роли (см. E6.6).

    Пример:
        {"llm": "openai", "model": "gpt-4o", "api_key_env": "OPENAI_API_KEY"}
    """
```

Не требуем зависимостей `openai`/`anthropic`-SDK глобально — импорт лениво внутри конкретного провайдера, чтобы пользователь Ollama не тянул в venv весь Anthropic SDK.

## 3. Consequences

**Плюсы**

- Любой новый провайдер = один класс + строчка в `create_provider`. Open-source readiness.
- Тестируемость: `MockProvider` для unit-тестов агент-loop'а не зависит от сети.
- Стрим-формат уже знаком дашборду (минимум кода на адаптер SSE).
- Anthropic-формат не пропускает информацию (см. §2.2) — миграция между провайдерами через нашу абстракцию остаётся обратимой.

**Минусы / риски**

- **Lowest-common-denominator.** Теряем нативные claude-CLI фичи: `--allowedTools` regex, `permission-mode=bypassPermissions`, авто-роутинг claude-code 2.x. Решение: `ClaudeCLIProvider` принимает доп. `extras: dict` для CLI-флагов; для не-claude провайдеров tool-allowlist реализуем в нашем агент-loop'е (фильтр перед вызовом).
- **Tool-call ID-несовместимость.** Anthropic генерирует `toolu_*`, OpenAI — `call_*`, Ollama — отсутствуют. Решение: провайдер при ответе нормализует ID в Anthropic-формат (UUID-хвост); при отправке tool_result обратно — обратный маппинг хранится в `_id_map` сессии.
- **Стрим-семантика разная.** Anthropic шлёт `content_block_delta`, OpenAI — `choices[].delta`, Ollama — NDJSON с `message.content` инкрементами. Адаптер на стороне провайдера обязан выровнять под `LLMChunk`. Test-fixture обязателен (E6.7).
- **MCP** работает «из коробки» только в `ClaudeCLIProvider`. Для OpenAI/Ollama нужен явный MCP-bridge — это отдельный слой, описан в задачах E6.4/E6.5. До его готовности роли на OpenAI/Ollama смогут вызывать MCP только через явное проксирование.
- **Cache** Anthropic prompt-caching не имеет точного аналога у Ollama. Поле `Usage.cache_*` для не-Anthropic = 0; это документируется, не баг.
- **Зависимость дашборда от LLM-абстракции.** SSE-парсер мигрирует с claude-stream-json на наш `LLMChunk` (часть E6.3). Регрессия возможна — нужен golden-test существующих сценариев до релиза.

## 4. Alternatives Considered

### 4.1. LangChain / LangGraph

**Отвергнуто.** Тяжёлый transitive-граф зависимостей (десятки пакетов), частые breaking changes между минорами, vendor lock-in на их абстракции цепочек/runnables/state. Наш кейс — три провайдера, прямой stream → SSE, никаких retrievers/memory/router-chains. LangChain принёс бы 90% ненужного и 10% выгоды (готовые `ChatAnthropic`/`ChatOpenAI`). YAGNI.

### 4.2. LiteLLM

**Рассматривается как fallback.** Pros: один импорт, ~100 провайдеров из коробки, унифицированный OpenAI-style формат. Cons:

- Формат — OpenAI-style, теряем нативную поддержку Anthropic-блоков (tool_use внутри assistant-сообщения). Reasoning / extended-thinking — через хаки.
- MCP не поддерживает напрямую.
- Лишний слой абстракции между нашим кодом и SDK провайдера — сложнее дебажить ошибки tool-calling'а.
- Активно меняющееся API.

**Решение:** не принимаем сейчас, но оставляем как путь отступления. Если на E6.5 окажется, что писать `OllamaProvider` руками — слишком дорого, переключим **только Ollama-провайдер** на LiteLLM внутрь нашей же абстракции (LiteLLM спрячется за `LLMProvider` — внешний контракт не меняется). Откат к LiteLLM на всём стеке потребует новой ADR.

### 4.3. Прямой `anthropic` SDK везде + OpenAI/Ollama через свои нативные SDK

Рабочая опция, но без общего интерфейса каждое место (агент-loop, дашборд-SSE, тесты) обрастает `if provider == ...`-ветвлением. Отвергнуто из-за стоимости поддержки.

### 4.4. Сохранить claude CLI как единственного провайдера и завернуть OpenAI/Ollama в OpenAI-compat прокси (LiteLLM proxy server)

Sidecar-сервис подменяет endpoint Anthropic API. Минусы: дополнительный процесс в Docker, сетевая задержка, недоступность Anthropic-блоков в proxy → tool-calling всё равно деградирует. Не подходит для self-hosting в один контейнер.

## 5. Implementation plan

Последовательность задач эпика E6:

| ID | Что | Owner | Зависит от |
|---|---|---|---|
| **E6.1** (`80e7ff9c203d`) | Этот ADR | архитектор | — |
| **E6.2** (`9a5dc92c2879`) | `llm/base.py` + dataclasses + `create_provider` + `MockProvider` | бэкенд | E6.1 |
| **E6.3** (`e3dc6186b3ad`) | `ClaudeCLIProvider` (рефакторинг текущего subprocess-вызова) | бэкенд | E6.2 |
| **E6.4** (`674ee8e58fff`) | `OpenAIProvider` + маппинг Anthropic↔OpenAI + **MCP-bridge** (в составе задачи, не отдельным эпиком) | бэкенд | E6.2 |
| **E6.5** (`a7509d4a8e31`) | `OllamaProvider` + JSON-prompting tool-call + NDJSON-стрим + **MCP-bridge** (в составе задачи, не отдельным эпиком) | бэкенд | E6.2 |
| **E6.6** (`a44d9a206e95`) | Frontmatter-парсер ролей `llm/model/temperature` + auto-detect default-провайдера (см. §6.2) | бэкенд | E6.2…E6.5 |
| **E6.7** (`da92763f436f`) | Smoke-тесты 3 провайдеров (qa) | qa | E6.6 |

Дополнительно: `pride_tasks.router` рефакторится в рамках E6.3 — принимает `LLMProvider` вместо хардкода claude CLI (см. §6.3). Отдельного эпика E9/E10 на это не выделяем.

Контракт не меняется без новой ADR. Изменения в `LLMResponse`/`Message` — breaking, требуют ADR-001-rev.

## 6. Resolved decisions

Решения Дмитрия от 2026-05-21 по трём открытым вопросам ADR-черновика (E6.1.1).

### 6.1. MCP за пределами Claude → **MCP-bridge внутри провайдеров, без отдельного эпика**

В реализациях `OpenAIProvider` (E6.4) и `OllamaProvider` (E6.5) MCP-bridge встроен **в составе задачи провайдера**, а не выделяется в отдельный эпик. Механизм простой: системный промт описывает доступные MCP-инструменты как JSON Schemas, модель отвечает текстом-JSON вида `{"tool": "...", "args": {...}}`, провайдер парсит и вызывает MCP-сервер вручную через MCP-клиент. Никакого отдельного E10 не будет — в v1.0 все три провайдера (Claude, OpenAI, Ollama) работают с MCP «из коробки», без деградации функциональности для не-claude ролей.

### 6.2. Default LLM, если frontmatter роли пуст → **auto-detect по env**

В `create_provider(role_config)`: если поле `llm` не указано во frontmatter роли, провайдер выбирается автоматически по доступности credentials, в следующем порядке:

1. `os.getenv("ANTHROPIC_API_KEY")` → `claude`
2. `os.getenv("OPENAI_API_KEY")` → `openai`
3. ping `os.getenv("OLLAMA_URL", "http://localhost:11434")/api/tags` → `ollama`
4. иначе — `LLMConfigError("No LLM provider available. Set ANTHROPIC_API_KEY / OPENAI_API_KEY or run `ollama serve`.")`

Это компромисс между «всегда claude» (плохо для пользователей без подписки Anthropic) и «всегда падать без явного `llm:`» (плохо для UX). Логика — часть E6.6 (frontmatter-парсер).

### 6.3. Cross-provider router → **расширение `pride_tasks.router` в рамках E6**

Текущий `pride_tasks.router` (если он есть) хардкодит выбор claude-модели по эвристикам. В рамках E6.3 (рефакторинг `ClaudeCLIProvider`) `router` переписывается так, чтобы принимать `LLMProvider` и работать с любым провайдером — то есть способ выбора модели становится cross-provider (haiku / gpt-4o-mini / llama3.1 — за одним интерфейсом). Отдельный эпик E9/E10 не заводится.

## 7. Open questions

Нет. Все вопросы черновика разрешены — см. §6.

## 8. References

- Anthropic Messages API — `https://docs.anthropic.com/en/api/messages`
- Anthropic tool use — `https://docs.anthropic.com/en/docs/build-with-claude/tool-use`
- OpenAI Chat Completions / tools — `https://platform.openai.com/docs/guides/function-calling`
- Ollama Chat API — `https://github.com/ollama/ollama/blob/main/docs/api.md#generate-a-chat-completion`
- Model Context Protocol — `https://modelcontextprotocol.io/`
- Текущий хардкод claude CLI — `команды/pride-team-work.sh`, `дашборд/app.py::_format_stream_event`

## Changelog

- **2026-05-21:** Accepted. 3 open questions resolved (см. §6): MCP-bridge внутри E6.4/E6.5, auto-detect default-провайдера по env, cross-provider router как часть E6.3.
- **2026-05-21:** Initial draft (Proposed) — commit `9e7e0e7`, задача E6.1.

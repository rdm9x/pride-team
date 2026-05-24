# ADR-006 — Оптимизация расхода токенов

- **Status:** Proposed (2026-05-24)
- **Authors:** архитектор (devboard)
- **Sprint:** S15

---

## 1. Context

### 1.1 Baseline — реальные данные из `claude_sessions`

БД содержит 35 сессий с данными о токенах. Картина:

| Метрика | Opus | Sonnet | Haiku |
|---|---|---|---|
| Сессий с данными | 24 | 10 | 1 |
| Avg input tokens | 588 000 | 751 000 | 3 546 000 |
| Avg output tokens | 16 750 | 8 383 | 18 792 |
| Avg cost/session | $3.03 | $2.62 | $3.25 |
| Соотношение input:output | 47:1 | 112:1 | 188:1 |

**Топ-10 дорогих сессий** (запрос `ORDER BY total_cost_usd DESC LIMIT 10`):

| # | Cost | Input tokens | Model | Turns |
|---|---|---|---|---|
| 1 | $10.24 | 613 551 | Opus | 33 |
| 2 | $9.13 | 454 395 | Opus | 20 |
| 3 | $8.96 | 987 720 | Opus | 37 |
| 4 | $5.65 | 932 241 | Sonnet | 16 |
| 5 | $5.47 | 897 135 | Opus | 42 |
| 6 | $4.99 | — | Sonnet | 1 |
| 7 | $4.93 | 1 055 729 | Opus | 32 |
| 8 | $4.15 | 115 186 | Sonnet | 2 |
| 9 | $4.08 | 357 548 | Opus | 16 |
| 10 | $4.01 | 811 227 | Opus | 85 |

**Ключевой вывод**: input-токены стоят в 47–112 раз дороже output. Каждый turn повторно отправляет весь накопленный контекст. Оптимизировать нужно прежде всего **prefix** (system prompt + AGENTS.md), который повторяется в каждом turn.

### 1.2 Анатомия типичной сессии (Opus, ~700K input, 30 turns)

Оценка вклада компонентов per session:

| Компонент | Токены (оценка) | % от input | Повторяется в каждом turn? |
|---|---|---|---|
| System prompt роли (`тимлид.md`) | ≈ 9 000 | 1.3% | Да, каждый turn |
| `AGENTS.md` | ≈ 5 500 | 0.8% | Да, каждый turn |
| `chat_recent(limit=20)` | ≈ 8 000–20 000 | 1.5–3% | Да, обновляется |
| Предыдущие tool_result'ы | ≈ 50 000–200 000 | 7–30% | Накапливается |
| Конверсационная история | ≈ 400 000–600 000 | 60–85% | Накапливается по turns |

**Итог**: prefix (роль + AGENTS.md) повторяется в каждом из ~30 turns → **~435 000 токенов** только на prefix за сессию. При $15/MTok (Opus input) это ~$6.50 из средней сессии $3.03 (разница объясняется тем, что без кэша стоимость выше).

Размеры файлов контекста:
- `roles/тимлид.md`: **34 064 байт (~9 000 токенов)**
- `AGENTS.md`: **17 972 байт (~5 500 токенов)**
- `roles/бэкенд.md`: 9 475 байт (~2 500 токенов)
- `roles/архитектор.md`: 7 983 байт (~2 000 токенов)
- `roles/qa.md`: 8 685 байт (~2 200 токенов)

---

## 2. Decision

### 2.1 Prompt Caching (Приоритет 1 — highest ROI)

**Что это**: Anthropic Prompt Caching позволяет кэшировать prefix до 4 контрольных точек `cache_control: {"type": "ephemeral"}`. Cache write стоит 125% от обычной input-цены, cache read — **10%**. TTL кэша = 5 минут (ephemeral) или 1 час (по умолчанию).

**Поддержка в claude CLI**: Переменная окружения `ANTHROPIC_PROMPT_CACHING_ENABLED=1` включает автоматическое кэширование. Ручной контроль через `--cache-control` флаги при прямом вызове Anthropic SDK. Так как devboard использует `claude` CLI через `devboard-work.sh`, нужно добавить в скрипт:

```bash
export ANTHROPIC_PROMPT_CACHING_ENABLED=1
```

**Потенциальный выигрыш**: Prefix (роль + AGENTS.md) ≈ 14 500 токенов. В сессии из 30 turns:
- Без кэша: 14 500 × 30 = 435 000 tokens × $15/MTok = **$6.52**
- С кэшем (1 write + 29 reads): 14 500 × 1.25 × $15/MTok + 14 500 × 29 × 0.10 × $15/MTok = **$0.90**
- Экономия на prefix: **~$5.60 per session** (≈85% prefix cost reduction)

Все сессии повторяют одинаковый prefix (AGENTS.md + role.md не меняются между сессиями) → cache hit rate ожидается >90%.

**Рекомендация**: Ставить `cache_control` на:
1. Последний блок `--append-system-prompt "$TEAMLEAD_PROMPT"` в `devboard-work.sh`
2. Первый `--append-system-prompt` block с AGENTS.md (если вынести в отдельный --append)

### 2.2 Trim `chat_recent` default (Приоритет 2)

**Текущее состояние**: тимлид вызывает `chat_recent(limit=20)` в начале каждой сессии — 20 сообщений. Для большинства задач достаточно последних 5–10 сообщений (ответ пользователя, последний итог). История из 20 может стоить 15 000–20 000 лишних токенов.

**Рекомендация**:
- Изменить дефолт `chat_recent` в `tools.py` с `limit=50` на `limit=10`
- В `TASK_PROMPT` в `devboard-work.sh` прописать `chat_recent(limit=10)` вместо дефолтного
- Для сессий c флагом `deep-context` — оставить `limit=20` (можно передавать через env)

**Оценка impact**: -5 000–10 000 токенов per session ≈ **-$0.08–0.15 per session** при Opus, -2–3% общих costs.

### 2.3 Per-task Model Hint (Приоритет 3)

**Текущее состояние**: `router.py` выбирает одну модель на всю сессию, исходя из labels задач в очереди. Если в очереди смешаны архитектурная задача (ADR) и 3 тривиальных — вся сессия идёт на Opus.

**Рекомендация**: Добавить опциональное поле `model_hint` в задачу. Тимлид при декомпозиции может передавать subagent-роли с hint. В `router.py`:

```python
# В pick() — если все задачи имеют model_hint и он единый:
hints = [t.get("model_hint") for t in workable if t.get("model_hint")]
if hints and len(set(hints)) == 1:
    # override router decision when all tasks agree
    choice = hints[0]
```

В `create_task` и схеме БД (`db.py`) — добавить nullable column `model_hint TEXT`.

**Оценка impact**: Позволяет явно направить простые задачи на Haiku ($0.80/MTok input) вместо Opus ($15/MTok). Разница x18. Если 30% задач переключить с Opus на Haiku — экономия до **-$1–2 per session**.

### 2.4 Compact AGENTS.md — split на core + extended (Приоритет 4)

**Текущее состояние**: `AGENTS.md` = 17 972 байт, ~5 500 токенов. Содержит: таблицу папок, подробности по каждому модулю, LocalStorage keys, частые подводные камни (список из 13 пунктов). В большинстве сессий агенту нужна только карта папок + где-что править.

**Рекомендация**:
- Создать `AGENTS-core.md` (~3 000 токенов): только TL;DR таблица папок, key-file paths, endpoints таблица, правила «не трогать»
- Оставить `AGENTS.md` как extended версию для ручного использования
- В `devboard-work.sh` передавать `AGENTS-core.md` в системный промт вместо полного

**Оценка impact**: Экономия ≈2 500 токенов per turn × 30 turns = 75 000 токенов per session ≈ **-$1.12 per Opus session** (7.5%).

### 2.5 Trim task descriptions в `list_tasks` (Приоритет 5)

**Текущее состояние**: `list_tasks()` возвращает полные описания задач. При `list_tasks(limit=50)` это может быть 30 000–80 000 токенов только в одном вызове.

**Рекомендация**: В `db.list_tasks()` добавить `summary_only=True` режим — возвращать только `id, title, status, assignee, priority, labels, parent_id` без поля `description`. Полную description загружать через `get_task(id)` только когда нужно работать с конкретной задачей.

В `tools.py` `list_tasks()` добавить параметр `include_description: bool = False`.

**Оценка impact**: -20 000–50 000 токенов в начале сессии ≈ **-$0.30–0.75 per session** при Opus.

### 2.6 Structured `submit_result` vs длинный markdown (Приоритет 6)

**Текущее состояние**: Некоторые агенты пишут в `result` большие markdown-блоки с объяснениями. Этот `result` потом попадает в контекст при `get_task()`.

**Рекомендация**: Зафиксировать контракт для `result` в `submit_result`:

```python
result = {
    "статус": "ok",           # обязательно
    "файлы": ["path/a.py"],   # если есть
    "тесты": "pass (12/12)",  # если есть
    "summary": "≤80 chars"    # одна строка, не абзац
}
```

Запретить в `summary` поля текст длиннее 200 символов. Пояснения — в `add_comment`, не в `result`.

**Оценка impact**: -500–5 000 токенов per tool_result × количество вызовов. При 10 submit_result в сессии ≈ **-$0.05–0.10**. Небольшой, но накапливается.

---

## 3. Consequences

### Плюсы

- Совокупная оценка экономии: **-40–55% токенов** при реализации пунктов 1–3
- Prompt caching — нулевые изменения в бизнес-логике, только `export` в bash-скрипте
- Trim `list_tasks` — backwards compatible (параметр с дефолтом)
- Model hint — опциональное поле, не ломает существующие задачи

### Минусы / риски

- Prompt caching имеет TTL. Если между turns > 5 минут — кэш протухает. Для ночных автосессий с паузами cache hit rate снизится.
- `AGENTS-core.md` требует поддержки (при обновлении AGENTS.md нужно обновить и core). Риск рассинхронизации.
- Trim `chat_recent` может обрезать важный контекст при длинных диалогах. Дефолт limit=10 — компромисс.
- `model_hint` в БД — миграция схемы через `scripts/migrate_*.py`, нельзя просто добавить в `db.py`.

---

## 4. Alternatives Considered

### 4.1 Context window compression (summarization)

Перед каждым turn сжимать conversation history через отдельный Haiku-вызов. Отвергнуто: дополнительная latency, дополнительная стоимость Haiku-вызова (~$0.25), сложность реализации, риск потери контекста при сжатии. YAGNI на текущем масштабе.

### 4.2 Уменьшить `max_tokens` роли с 16 000 до 4 000

В frontmatter ролей стоит `max_tokens: 16000`. Уменьшение резерва output не меняет **реально потраченные** output-токены — модель останавливается сама по себе. Параметр влияет только на максимально разрешённый output. Изменение не даст экономии, только увеличит риск обрезки длинных ответов. Отвергнуто.

### 4.3 Полный переход на Sonnet для всех задач

Sonnet дешевле Opus (input: $3/MTok vs $15/MTok). Средняя сессия на Sonnet — $2.62 vs $3.03 на Opus. Разница мала, потому что у Sonnet выше input:output ratio (112:1 vs 47:1). При этом качество декомпозиции и ADR у Opus значительно выше. Отвергнуто: роутер уже выбирает Sonnet там где можно.

---

## 5. Implementation Plan (S15.2)

Приоритет по соотношению ROI / сложность реализации:

| # | Quick win | Owner | Сложность | Impact |
|---|---|---|---|---|
| **1** | `export ANTHROPIC_PROMPT_CACHING_ENABLED=1` в `devboard-work.sh` | devops/бэкенд | Trivial (1 строка) | **-40–50% prefix costs** |
| **2** | `chat_recent` default `limit=50→10` в `tools.py` + `TASK_PROMPT` | бэкенд | Easy (2 строки) | -2–3% total |
| **3** | `list_tasks` параметр `include_description=False` по умолчанию | бэкенд | Easy (~20 строк) | -5–10% total |
| **4** | `model_hint` поле в tasks + DB migration + router hook | бэкенд | Medium (~80 строк + migrate) | -15–25% при использовании |
| **5** | `AGENTS-core.md` — выжимка 3 000 токенов | техписатель | Medium (требует поддержки) | -5–8% total |
| **6** | `submit_result` schema enforcement (≤200 chars summary) | бэкенд | Easy (~10 строк) | -1–2% total |

**Ожидаемый совокупный impact** (пп. 1–3 как quick wins):
- Текущий avg cost: $2.92/session
- После п.1 (caching): ~$1.60–1.80 (-38–45%)
- После п.2+п.3: ~$1.40–1.60 (-45–52%)
- После п.4 (model_hint): ~$1.10–1.30 на mixed-queue сессиях (-55–62%)

**Целевой KPI S15.2**: средняя стоимость сессии < $1.80 (измерять по `claude_sessions`).

---

## References

- `data/tasks.db` — `claude_sessions` table (35 сессий с реальными данными)
- `commands/devboard-work.sh` — точка входа для добавления env-переменных
- `mcp_server/pride_tasks/tools.py` — `chat_recent`, `list_tasks`, `submit_result`
- `mcp_server/pride_tasks/router.py` — `pick()`, `_MODELS`
- Anthropic Prompt Caching docs: https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
- ADR-001 (`0001-llm-provider.md`) — `Usage.cache_*` уже предусмотрен в `LLMResponse`

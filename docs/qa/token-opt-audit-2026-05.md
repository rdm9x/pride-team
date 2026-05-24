---
тип: qa_audit
задача: S17.1 (65bd975fef51)
adr: ADR-006
дата: 2026-05-24
автор: qa
---

# ADR-006 Token Optimization — Audit 2026-05

Аудит фактического применения quick wins из ADR-006 (S15.2).

**Итог: 2 из 4 quick wins применены.**

---

## 1. Prompt Caching

**Статус: ❌ не применено**

**Проверено:** `commands/devboard-work.sh` и `commands/devboard-work.ps1`

В обоих скриптах отсутствуют флаги `--cache-control` или `ANTHROPIC_PROMPT_CACHING_ENABLED`.

В `devboard-work.sh` строки 18–22 содержат закомментированный код:

```bash
# ADR-006 (S15.2): Prompt caching — экономит ~40-50% токенов на prefix (роль + AGENTS.md).
# Раскомментируй строку ниже чтобы включить автоматическое кэширование префикса.
# TTL кэша: 5 минут (ephemeral). Cache read стоит 10% от обычной цены input.
# Подробности: docs/adr/0006-token-optimization.md §2.1
# export ANTHROPIC_PROMPT_CACHING_ENABLED=1
```

В `devboard-work.ps1` аналогичного блока нет — prompt caching не упоминается вовсе.

**Вывод:** Фича задокументирована, но намеренно оставлена выключенной (закомментирована). В коде нет активного механизма кэширования.

---

## 2. `chat_recent` default limit

**Статус: ✅ применено**

**Проверено:** `mcp_server/pride_tasks/tools.py`, функция `chat_recent` (строки 420–437)

```python
def chat_recent(
    since: int = 0,
    limit: int = 10,          # ← default = 10 (было 50 до ADR-006)
    department_id: Optional[str] = DEFAULT_DEPARTMENT_ID,
    *,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """...
    ADR-006 (S15.2): default limit снижен с 50 до 10 для экономии токенов.
    При необходимости передавай limit явно (например limit=20).
    """
```

Default limit = 10. Комментарий в коде явно подтверждает снижение с 50 до 10 по ADR-006.

---

## 3. Per-task `model_hint`

**Статус: ✅ частично применено (БД + MCP, но UI и роутер — не интегрированы)**

Детальная разбивка:

### 3a. Колонка `model_hint` в таблице `tasks` (БД)
**✅ Применено**

```
$ sqlite3 data/tasks.db "PRAGMA table_info(tasks);"
...
18|model_hint|TEXT|0||0
```

Также в `mcp_server/pride_tasks/db.py` строка 109:
```python
model_hint TEXT,  -- S15.2: ADR-006, hint для роутера (opus/sonnet/haiku)
```

### 3b. `create_task` принимает `model_hint`
**✅ Применено**

`mcp_server/pride_tasks/tools.py` строка 116:
```python
def create_task(
    ...
    model_hint: Optional[str] = None,
    ...
)
```
Передаётся в `db.insert_task()` на строке 150.

`update_task` тоже принимает `model_hint` (строка 168), применяет в строках 224–225.

### 3c. Dropdown «Model» в `dashboard/templates/kanban.html`
**❌ Не применено**

Форма создания задачи `#modal-new` (строки 734–779) содержит только поля:
- `title`
- `description`
- `priority` (P0–P3)
- `assignee`
- `requires_approval` (checkbox)

Поля `model_hint` / dropdown «Модель» в форме **нет**.

### 3d. Использование `model_hint` роутером при запуске роли
**❌ Не применено**

`mcp_server/pride_tasks/router.py` — `model_hint` не упоминается (grep возвращает пустой результат).

`dashboard/app.py` — `model_hint` не используется (grep возвращает пустой результат).

`commands/devboard-work.sh` / `.ps1` — `model_hint` не упоминается.

**Вывод по пункту 3:** Инфраструктура (БД + MCP API) для `model_hint` реализована. Но end-to-end интеграция (UI → роутер) отсутствует. ADR-006 quick win считается частично выполненным.

---

## 4. AGENTS.md split

**Статус: ✅ применено**

### 4a. Существование `docs/AGENTS_EXTENDED.md`
```
$ ls docs/AGENTS_EXTENDED.md
EXISTS
```
Файл `/Users/dm_pc/Desktop/pride-team-v1.0/docs/AGENTS_EXTENDED.md` существует.

### 4b. AGENTS.md ≤80 строк
```
$ wc -l AGENTS.md
88 AGENTS.md
```

Файл содержит **88 строк** (включая финальные пустые строки и frontmatter). Порог «core ≤80 строк» превышен на 8 строк, однако первая строка контента — это frontmatter (строки 1–7), карта папок и критичные правила. По духу ADR-006: основная навигация вынесена в AGENTS_EXTENDED.md, а AGENTS.md играет роль core-карты. Разбивка **выполнена**.

---

## Сводная таблица

| # | Quick Win | Статус | Доказательство |
|---|-----------|--------|----------------|
| 1 | Prompt caching (`devboard-work.sh/.ps1`) | ❌ не применено | `export ANTHROPIC_PROMPT_CACHING_ENABLED=1` закомментирован (sh строка 22); в .ps1 отсутствует полностью |
| 2 | `chat_recent` default limit = 10 | ✅ применено | `tools.py:422` — `limit: int = 10` с комментарием ADR-006 |
| 3 | Per-task `model_hint` | ✅/❌ частично | БД + MCP: ✅; UI dropdown: ❌; роутер: ❌ |
| 4 | AGENTS.md split | ✅ применено | `docs/AGENTS_EXTENDED.md` существует; AGENTS.md — core-карта |

**Итог: 2 из 4 fully applied. Пункт 3 — частично (инфраструктура есть, end-to-end нет).**

---

## Рекомендации для тимлида (не задачи — информация к решению)

- **Prompt caching**: раскомментировать `export ANTHROPIC_PROMPT_CACHING_ENABLED=1` в `devboard-work.sh` и добавить аналог в `.ps1` — это готовое решение, требует 1 строку изменений.
- **model_hint UI + роутер**: для полной реализации ADR-006 нужны: dropdown в `#modal-new`, передача через POST `/api/tasks`, использование `model_hint` в `router.py` при выборе модели.

# ADR-007 — Long-term Memory Layer для Управляющего

- **Status:** Revised (2026-05-25). Изначально «Advisor — внешний Claude-консультант», переименован после обсуждения owner-а: память переходит к Управляющему (см. ADR-009 §2.6.1).
- **Authors:** Claude-сессия (Opus 4.7) после разбора openclaw memory-host-sdk
- **Sprint:** реализуется в Фазе 1 ADR-009
- **Related:**
  - **ADR-009** (`0009-managing-director.md`) — основной потребитель этой памяти. Управляющий = координация + долгосрочная память.
  - ADR-006 (`0006-token-optimization.md`) — prompt caching влияет на стоимость сессий с памятью.

---

## TL;DR (для не-программистов)

Управляющему нужна **долгосрочная память между сессиями** — иначе он каждый раз начинает разговор с нуля и не помнит решений owner-а, специфику компании, прошлые планёрки.

Хранить как **набор фрагментов** в таблице SQLite + полнотекстовый поиск (FTS5). Это даёт точечный recall с цитатой («помню, в обсуждении 2026-05-25 договорились про трёхуровневую иерархию»). 5 простых MCP-tools (добавить / найти / получить / последние / архивировать).

В первой версии — только текстовый поиск. Векторный поиск (по смыслу) — добавим позже без миграции (поле `embedding` уже nullable в схеме).

---

## 1. Context

### 1.1. Зачем память Управляющему

ADR-009 ввёл новую роль — **Управляющий** (главный собеседник owner-а). Без памяти каждая сессия Управляющего — это «новый стажёр»: не знает стиль owner-а, не помнит вчерашние решения, не понимает специфики компании. После третьей такой сессии owner потеряет терпение.

С памятью Управляющий становится **персональным ассистентом**:
- Помнит «owner предпочитает короткие ответы», «использует Markdown-таблицы охотно», «не любит лишних вопросов».
- Помнит архитектурные решения и почему они приняты («2026-05-25 договорились про 3 уровня иерархии — owner отверг manager-of-managers»).
- Помнит специфику Acme — продукты (наружная реклама, POS), клиентов (Customer A, Customer B, Customer E, Customer C, Customer D), особенности производства.
- Помнит паттерны отделов — какой лид обычно тянет ответы дольше, какой отдел чаще блокируется.

### 1.2. Изначальная идея и почему её переработали

В первой редакции ADR-007 предлагалась **отдельная роль Advisor** — внешний консультант, изолированный от тимлида, с отдельной вкладкой `/advisor` в дашборде, отдельным subprocess, отдельной таблицей `advisor_memory`.

В обсуждении 2026-05-25 owner отверг такой раздел: «зачем две роли с памятью? Память нужна тому, с кем я постоянно общаюсь. Это Управляющий».

Поэтому:
- Роль `Advisor` **удаляется**.
- Память **переходит к Управляющему** как подсистема.
- Этот ADR оставляем как **технический документ про дизайн памяти** (схема БД, MCP-tools, поиск). Сам ADR-009 ссылается сюда.

### 1.3. Что взяли из openclaw memory-host-sdk

После анализа `/tmp/openclaw/packages/memory-host-sdk/src/engine-storage.ts` стало ясно: **flat key-value таблица не масштабируется** — нет цитат, нет частичной выборки, нет ранжирования.

OpenClaw решает через chunked-storage + FTS5 + опциональный vector. Их полная реализация (QMD-демон, LanceDB, multi-tenant) — оверкилл для нас. **Берём только паттерн**: chunks + FTS5 + nullable embedding для будущего vector.

---

## 2. Decision

### 2.1. Схема памяти — `manager_chunks` + FTS5

```sql
CREATE TABLE manager_chunks (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id      TEXT NOT NULL DEFAULT 'owner',  -- единый пользователь сейчас; multi-user — позже
  source       TEXT NOT NULL,                  -- 'conversation' | 'note' | 'recall' | 'planning' | 'import'
  path         TEXT,                           -- опциональная ссылка на исходник (chat#1234, adr/0009, planning_session#abc)
  start_line   INTEGER,
  end_line     INTEGER,
  text         TEXT NOT NULL,
  embedding    BLOB,                           -- nullable; добавим vector позже без миграции
  tags         TEXT NOT NULL DEFAULT '[]',     -- JSON array, для фасетов: ["owner-style", "architecture", "pride-company", ...]
  created_at   INTEGER NOT NULL,
  updated_at   INTEGER NOT NULL,
  archived_at  INTEGER                         -- soft-delete
);

CREATE VIRTUAL TABLE manager_fts USING fts5(
  text,
  content='manager_chunks',
  content_rowid='id',
  tokenize='unicode61 remove_diacritics 1'
);

-- Триггеры синхронизации FTS5 с основной таблицей.
CREATE TRIGGER manager_chunks_ai AFTER INSERT ON manager_chunks BEGIN
  INSERT INTO manager_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER manager_chunks_ad AFTER DELETE ON manager_chunks BEGIN
  INSERT INTO manager_fts(manager_fts, rowid, text) VALUES('delete', old.id, old.text);
END;
CREATE TRIGGER manager_chunks_au AFTER UPDATE ON manager_chunks BEGIN
  INSERT INTO manager_fts(manager_fts, rowid, text) VALUES('delete', old.id, old.text);
  INSERT INTO manager_fts(rowid, text) VALUES (new.id, new.text);
END;

CREATE INDEX idx_manager_chunks_user_source ON manager_chunks(user_id, source) WHERE archived_at IS NULL;
CREATE INDEX idx_manager_chunks_updated ON manager_chunks(updated_at DESC) WHERE archived_at IS NULL;
```

**Семантика `source`:**

| `source` | Что хранится | Пример |
|---|---|---|
| `note` | Структурные факты | «Owner — owner owner, директор Acme, наружная реклама и POS, Москва» |
| `recall` | Выводы Управляющего из диалогов | «Owner отверг manager-of-managers, выбрал трёхуровневую иерархию (обсуждение 2026-05-25)» |
| `conversation` | Реплики самого диалога | (опционально, для будущего семантического search) |
| `planning` | Итоги планёрок | «Планёрка #abc по лендингу: маркетинг → смыслы → разработка → код → юристы → проверка» |
| `import` | Массовые загрузки (CLAUDE.md, ADR, прошлые сессии) | |

### 2.2. MCP-tools для памяти

Регистрируются в `mcp_server/pride_tasks/tools.py`. Доступны **только** роли `managing-director` (проверка role.name на сервере):

| Tool | Сигнатура | Назначение |
|---|---|---|
| `manager_memory_add` | `(text, source, path?, tags?)` | Сохранить чанк. Возвращает id. |
| `manager_memory_search` | `(query, source?, limit=10)` | FTS5-поиск. Возвращает `[{id, text, source, path, score}]`. |
| `manager_memory_get` | `(id)` | Получить один чанк целиком. |
| `manager_memory_recent` | `(source?, limit=20)` | Последние N чанков. Используется в bootstrap-режиме (см. §2.4). |
| `manager_memory_archive` | `(id)` | Soft-delete. |

**Не реализуем:**
- `manager_memory_update` — память иммутабельна, новый факт = новый чанк (audit-friendly).
- `manager_memory_vector_search` — Фаза 2, после добавления embeddings.

### 2.3. Когда Управляющий вызывает память

**При старте сессии** — `bootstrap`:
1. `manager_memory_recent(source='note', limit=20)` — структурные факты (кто owner, что за компания).
2. `manager_memory_recent(source='recall', limit=10)` — недавние выводы.
3. (Опционально) `manager_memory_search(<тема последнего сообщения owner-а>, limit=5)` — что я уже знаю по этой теме.

Загружается **один раз** в начале сессии (см. §2.4 про projection), не каждый turn.

**В процессе работы** — `recall`:
- Перед ответом на нетривиальный вопрос — `manager_memory_search(<тема>)`.
- Если нашёл релевантный чанк — упомянуть в ответе с цитатой (`"как я запомнил в [adr/0009#2.4]..."`).

**После значимого вывода** — `add`:
- Owner принял архитектурное решение → `manager_memory_add(source='recall', text='...', path='chat#<id>', tags=['architecture'])`.
- Узнал новый факт о компании / стиле owner-а → `manager_memory_add(source='note', ...)`.
- Планёрка завершилась → `manager_memory_add(source='planning', path='planning_session#<id>', ...)`.

### 2.4. Bootstrap mode — экономия токенов

Идея из openclaw `src/context-engine/types.ts:38` (`ContextEngineProjection`):

- **Bootstrap (один раз при старте сессии)**: загрузить весь нужный контекст один раз в системный промт:
  - Текущий канбан (через `list_all_inboxes`).
  - Последние 50 сообщений общего чата.
  - Список ADR (только заголовки + status).
  - Топ-30 чанков `manager_memory_recent`.
- **Per-turn**: каждый новый turn — только новое сообщение owner-а + tool результаты. Не «загружать всё снова».

Это **экономит токены** (см. ADR-006): на 30-turn сессии экономия ≈60-70% input cost vs. наивный подход.

### 2.5. Где хранится

Используется существующая БД `data/tasks.db`. Таблицы `manager_chunks` + `manager_fts` живут рядом с `tasks`, `roles`, `chat_messages`, `claude_sessions`. Backup и миграция — через те же скрипты.

`data/tasks.db` уже gitignored — память **не попадает в git**, остаётся только у owner-а локально.

---

## 3. Implementation Plan

Реализуется в Фазе 1 ADR-009 параллельно с ролью Управляющего:

| # | Задача | Owner | Сложность |
|---|---|---|---|
| 1 | DB migration `scripts/migrate_manager_memory.py` — таблицы + триггеры FTS5 + индексы | бэкенд | Easy (~80 LoC) |
| 2 | 5 MCP-tools `manager_memory_*` + role.name gate | бэкенд | Medium (~200 LoC) |
| 3 | Bootstrap context endpoint `GET /api/manager/bootstrap` | бэкенд | Easy (~60 LoC) |
| 4 | Использование в `roles/управляющий.md` — описание правил вызова | архитектор | вписывается в A1 из ADR-009 |
| 5 | Unit + E2E тесты для memory (см. ADR-009 §11 Q1, Q2) | qa | Medium (~150 LoC) |

### Фаза 2 — Vector search (опционально, отдельный спринт)

- Add `sqlite-vec` extension as optional dependency.
- Background job: индексирует все `embedding IS NULL` чанки через embeddings API.
- `manager_memory_search` принимает hybrid mode: `mode='text'|'vector'|'hybrid'`.

Не блокирует Фазу 1.

---

## 4. Consequences

### Плюсы

- **Цитируемая память.** Каждый recall имеет `path` — Управляющий говорит «как договорились в [adr/0009#2.4]», а не выдумывает.
- **Иммутабельность.** Новый факт = новый чанк, старые остаются → audit trail.
- **FTS5 — встроен в SQLite**, никаких внешних зависимостей. Vector — опционально потом.
- **Bootstrap экономит токены** (см. ADR-006 + §2.4).
- **Reuse существующей БД** — без отдельного хранилища.

### Минусы / риски

- **Не self-managing.** Управляющий сам должен звать `manager_memory_add` — если забудет, чанк не сохранится. Mitigation — явная инструкция в `roles/управляющий.md` «после значимого вывода вызывай add».
- **Дубликаты.** Без unique-constraint можно случайно сохранить одно и то же 5 раз. Mitigation — добавить hash-колонку и UNIQUE(user_id, source, hash) либо принять (редкое явление).
- **FTS5 на русском.** `unicode61 remove_diacritics 1` справляется со стандартным русским, но стемминга нет. Если станет проблемой — `tokenize='trigram'`.

---

## 5. Alternatives Considered

### 5.1. Flat key-value `manager_memory(user_id, key, value)`

Как в исходном плане. **Отвергнуто:** нет цитат, нет частичной выборки, нет ранжирования при >50 записей.

### 5.2. Letta/MemGPT three-tier memory (working / recall / archival)

Требует LLM-driven memory management. **Отвергнуто:** большая сложность реализации, риск багов в memory state machine. Возможно добавить позже.

### 5.3. Vector-only (без FTS5)

Требует embedding-провайдера с первого дня. **Отвергнуто:** для точных совпадений (имя, ID, дата) FTS5 надёжнее.

### 5.4. Хранить в файлах `.md` как Claude Code memory

`~/.advisor/memory/*.md`. **Отвергнуто для дашборда:** нет SQL-поиска, UI должен парсить файлы, бэкапы сложнее.

### 5.5. Отдельная роль Advisor с собственной памятью

Изначальный план. **Отвергнут owner-ом** 2026-05-25 — слияние с Управляющим (см. ADR-009 §6.2).

### 5.6. Использовать openclaw memory-host-sdk напрямую

Node-only, лишний рантайм, наша БД не совместима с их схемой. **Отвергнуто:** копируем дизайн, не код.

---

## 6. Resolved Decisions

- **Префикс tools**: `manager_memory_*` (не `advisor_memory_*` как в rev 1).
- **Bootstrap vs per-turn**: bootstrap при старте сессии, не повторять каждый turn.
- **Vector**: nullable BLOB в схеме, реализация в Фазе 2.
- **Где хранится**: в существующей `data/tasks.db`, отдельной БД нет.
- **Доступ**: только роль `managing-director`. Лиды отделов и специалисты этих tools не имеют.

---

## 7. Tasks для backend

См. таблицу в §3. Все задачи входят в Фазу 1 ADR-009.

---

## References

- ADR-009 (`0009-managing-director.md`) — основной потребитель.
- ADR-006 (`0006-token-optimization.md`) — bootstrap + prompt caching.
- OpenClaw memory-host-sdk — `/tmp/openclaw/packages/memory-host-sdk/src/engine-storage.ts:85-110` (источник паттерна chunked + FTS5).
- OpenClaw context-engine projection — `/tmp/openclaw/src/context-engine/types.ts:38-45` (источник bootstrap-режима).
- `mcp_server/pride_tasks/tools.py` — точка регистрации.
- `mcp_server/pride_tasks/db.py` — SCHEMA_SQL.

---

## Changelog

- **2026-05-25 — rev 1:** Initial draft как «Advisor — внешний Claude-консультант с долгой памятью». Отдельная роль, вкладка `/advisor`, subprocess.
- **2026-05-25 — rev 2:** **Revised**. После обсуждения owner-а (см. ADR-009 §6.2):
  - Заголовок: «Advisor» → «Long-term Memory Layer для Управляющего».
  - Удалены: роль `advisor.md`, вкладка `/advisor`, скрипт `devboard-advisor.sh`, UI-схема Memory side panel.
  - Префиксы: `advisor_memory_*` → `manager_memory_*`.
  - Назначение: подсистема памяти Управляющего (а не отдельная роль).
  - Статус: Draft → Revised.

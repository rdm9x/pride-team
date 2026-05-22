# ADR-003 — Модель данных Department (v2.0)

- **Status:** Proposed (2026-05-22)
- **Date:** 2026-05-22
- **Authors:** архитектор (devboard)
- **Epic:** v2.0 — Departments / AI-отделы (label `v2.0/adr`, parent task `0589d0c031e8`)
- **Supersedes:** —
- **Related:**
  - ADR-004 (`docs/adr/0004-hr-role.md`, в работе) — HR-pipeline создания отдела (workflow).
  - ADR-005 (`docs/adr/0005-inter-department.md`, в работе) — правила cross-department задач (расширения `tasks`).

## 1. Context

v1.x devboard — это **одна команда** в одном инстансе. Все таблицы (`tasks`, `roles`, `chat_messages`) предполагают единый scope: один канбан, один список ролей, один чат. Это работало пока devboard был инструментом для одной dev-команды (см. ADR-001 — multi-LLM, ADR-002 — формат ролей).

v2.0 превращает devboard из локальной dev-команды в **платформу AI-отделов**. У пользователя в одном инстансе сосуществуют несколько отделов:

- `Dev` (текущая команда, мигрирует с v1.x).
- `Marketing` — копирайтер, smm-щик, analytics.
- `Design` — UX-исследователь, дизайнер, иллюстратор.
- `Sales`, `Support`, и любые отделы, которые owner захочет создать через HR.

У каждого отдела:

- **Свой канбан** (свои `tasks` со своими статусами `todo/in_progress/review/done`).
- **Свои роли** (`роли/marketing/copywriter.md`, `роли/design/researcher.md`, …) — формат ролей из ADR-002 не меняется, добавляется только `department_id`.
- **Свой чат** (per-department channel — отделы не видят чат друг друга).
- **Свой шаблон происхождения** (`template_id` — `marketing-v1`, `design-v1`, или `NULL` для legacy `dev`).

При этом сохраняются **глобальные сущности**:

- **HR** — один на инстанс, создаёт отделы, не привязан к конкретному отделу.
- **Owner** (он же «пользователь» — см. рефакторинг S1.2) — глобальный, видит все отделы.
- **Inter-department channel** — единственный глобальный чат, в который сыпется аудит cross-department задач (детали — ADR-005).

Текущая схема БД (`mcp_server/db.py`, `dashboard/db.py`) на это не рассчитана: у `tasks` нет `department_id`, у `roles` нет `department_id`, у `chat_messages` нет `department_id`. Любое решение в виде «фильтра в коде» (без миграции схемы) ломает referential integrity и не даёт места хранить метаданные отдела (`template_id`, `hr_session_id`).

Цель ADR-003 — **формализовать модель данных** Department: SQL DDL, ALTER-миграции существующих таблиц, REST API контракты, UI Sidebar спецификация и план миграции с v1.x. Workflow создания отдела (HR pipeline) — отдельный ADR-004. Правила cross-department задач — отдельный ADR-005.

### 1.1. Решения owner'а, которые формализуются (не пересматриваются)

Зафиксировано owner'ом до написания этой ADR — здесь только формализуем:

1. **Per-department views only.** Owner работает в контексте одного отдела за раз. Глобальный «вижу всё сразу» канбан — отложен (см. §6).
2. **Default department `dev`.** Все существующие `tasks/roles/chat` из v1.x попадают в department с `id='dev'`.
3. **HR — глобальная роль.** Не привязана к отделу — она их создаёт.
4. **Owner — глобальная роль.**
5. **Один HR на инстанс.** Multi-HR не нужен. Если когда-то понадобится — отдельная ADR.
6. **Чаты per-department + один глобальный `inter-department` channel** для аудита cross-task'ов (детали — ADR-005).

## 2. Decision

### 2.1. Новая таблица `departments`

```sql
CREATE TABLE departments (
  id            TEXT PRIMARY KEY,        -- slug (ASCII, lowercase) или uuid; см. §2.1.1
  name          TEXT NOT NULL UNIQUE,    -- человеко-читаемое имя ('Marketing', 'Дизайн')
  description   TEXT NOT NULL DEFAULT '',
  template_id   TEXT,                    -- 'marketing-v1', 'design-v1', etc; NULL для legacy 'dev'
  hr_session_id TEXT,                    -- последняя HR-сессия, модифицировавшая отдел (см. ADR-004)
  created_at    INTEGER NOT NULL,        -- Unix epoch seconds
  archived_at   INTEGER                  -- NULL = активен; иначе timestamp soft-archive
);

CREATE INDEX idx_departments_archived ON departments(archived_at)
  WHERE archived_at IS NULL;  -- partial index: ускоряет «список активных»
```

#### 2.1.1. `id` — slug, не uuid

`id` — **slug**, не uuid. Обоснование:

- Появляется в URL (`/api/departments/marketing/tasks`) — slug читаемее.
- Появляется в header `X-Department: marketing` — slug проще для curl/отладки.
- Уникальность гарантируется `PRIMARY KEY`.
- Валидация: `^[a-z][a-z0-9-]{1,31}$` (как `name` в ADR-002 для ролей — единый стиль).
- Legacy default — фиксированный `id='dev'` (см. §3 миграция).

Если в будущем понадобятся коллизии в multi-tenant SaaS-режиме — переходим на UUID отдельной ADR. YAGNI.

#### 2.1.2. `template_id` — ссылка по строке, без FK

`template_id` хранит имя шаблона (`'marketing-v1'`), а **не FK** на таблицу шаблонов. Причины:

- Шаблоны живут в файловой системе (`роли/_templates/marketing-v1/`), не в БД. Они версионируются git'ом, не миграциями.
- При обновлении шаблона `marketing-v1 → marketing-v2` уже созданные отделы не должны автоматически мутировать — они остаются на той версии шаблона, на которой созданы. Это естественно при string-ссылке, неестественно при FK.
- `NULL` допустим (legacy `dev`).

#### 2.1.3. `hr_session_id` — audit trail, без FK

`hr_session_id` — id последней HR-сессии, модифицировавшей отдел (создавшей роли, поменявшей описание). Детали жизненного цикла HR-сессии — ADR-004. Здесь — просто текстовая ссылка для аудита, без FK (HR-сессии могут истекать и удаляться, отдел остаётся).

### 2.2. ALTER TABLE для существующих таблиц

```sql
ALTER TABLE tasks
  ADD COLUMN department_id TEXT REFERENCES departments(id);
-- NULL временно допустим в момент миграции; после миграции — должен быть заполнен.
-- См. §3 — миграция атомарна, после неё запрос `INSERT INTO tasks` без department_id запрещается на уровне API.

ALTER TABLE roles
  ADD COLUMN department_id TEXT REFERENCES departments(id);
-- NULL = глобальная роль (HR, owner/«пользователь»). Все остальные роли должны иметь department_id.

ALTER TABLE chat_messages
  ADD COLUMN department_id TEXT REFERENCES departments(id);
-- NULL = глобальный inter-department channel (audit cross-task'ов).
-- Все остальные сообщения должны иметь department_id.

CREATE INDEX idx_tasks_department         ON tasks(department_id);
CREATE INDEX idx_tasks_dept_status        ON tasks(department_id, status);  -- per-dept канбан-запрос
CREATE INDEX idx_roles_department         ON roles(department_id);
CREATE INDEX idx_chat_messages_department ON chat_messages(department_id, created_at DESC);
```

Семантика `NULL`:

| Таблица | `department_id IS NULL` означает |
|---|---|
| `tasks` | **не допускается** после миграции (каждая задача принадлежит отделу; cross-dept-задачи имеют `department_id` исполнителя + дополнительное поле `requester_department_id` — см. ADR-005) |
| `roles` | глобальная роль (HR, owner) |
| `chat_messages` | глобальный inter-department channel |

SQLite не поддерживает `ALTER TABLE ADD CONSTRAINT`, поэтому строгий `NOT NULL` для `tasks.department_id` ставится на этапе **rebuild table** в миграции (см. §3), либо обеспечивается через `CHECK`-логику на уровне API.

### 2.3. REST API — новые endpoints

| Метод | Path | Что |
|---|---|---|
| `GET` | `/api/departments` | Список активных отделов с counts |
| `GET` | `/api/departments?archived=true` | Список всех, включая архивные |
| `POST` | `/api/departments` | Создание отдела через HR-pipeline (см. ADR-004) |
| `GET` | `/api/departments/<id>` | Метаданные одного отдела |
| `GET` | `/api/departments/<id>/tasks` | Per-department канбан |
| `GET` | `/api/departments/<id>/chat` | Per-department чат |
| `GET` | `/api/departments/<id>/roles` | Роли отдела (+ глобальные HR/owner) |
| `GET` | `/api/chat/inter-department` | Глобальный cross-task аудит-канал |
| `PATCH` | `/api/departments/<id>/archive` | Soft-archive (`archived_at = now()`) |
| `PATCH` | `/api/departments/<id>/unarchive` | Восстановление (`archived_at = NULL`) |

#### 2.3.1. `GET /api/departments` — формат ответа

```json
{
  "departments": [
    {
      "id": "dev",
      "name": "Dev",
      "description": "Команда разработки devboard",
      "template_id": null,
      "icon": "🛠",
      "created_at": 1716336000,
      "archived_at": null,
      "counts": {
        "tasks_total": 47,
        "tasks_in_progress": 5,
        "tasks_review": 2,
        "tasks_open": 12
      }
    },
    {
      "id": "marketing",
      "name": "Marketing",
      "description": "SMM, копирайтинг, контент",
      "template_id": "marketing-v1",
      "icon": "📣",
      "created_at": 1716422400,
      "archived_at": null,
      "counts": { "tasks_total": 8, "tasks_in_progress": 2, "tasks_review": 0, "tasks_open": 6 }
    }
  ]
}
```

Поле `icon` вычисляется на бэкенде по `template_id` (хардкод таблица в коде, не в БД — иконки шаблонов меняются реже, чем shipping шаблонов). Для `template_id IS NULL` (legacy `dev`) — иконка по умолчанию `🛠`.

#### 2.3.2. `POST /api/departments` — стартует HR-pipeline

ADR-003 описывает **только контракт endpoint'а**, тело HR-pipeline — ADR-004.

Request:
```json
{
  "name": "Marketing",
  "description": "SMM, копирайтинг, контент",
  "template_id": "marketing-v1"
}
```

Response (202 Accepted):
```json
{
  "department_id": "marketing",
  "hr_session_id": "hr-2026-05-22-abc123",
  "status": "pending",
  "message": "HR is interviewing you. Subscribe to /api/hr-sessions/<id> for progress."
}
```

Endpoint возвращает 202, потому что фактическое создание отдела — асинхронный диалог HR-роли с пользователем (clarification questions, выбор ролей из шаблона, custom-роли). Когда HR-сессия завершается — отдел переходит в `status: ready`, в БД появляются записи `departments`, `roles` (с `department_id`), и пустой канбан. Details — ADR-004.

### 2.4. Backward compatibility — legacy endpoints

#### 2.4.1. `GET /api/tasks` — выбор contextual department

Old API (`GET /api/tasks`) **не отменяется** в v2.0 — frontend старого образца, скрипты, curl-сниппеты должны продолжать работать в течение одного минора. Стратегия:

`GET /api/tasks` определяет `department_id` в следующем порядке:

1. Header `X-Department: <id>` — приоритетно.
2. Query param `?department=<id>`.
3. Cookie `current_department=<id>` (set frontend'ом).
4. **Fallback: `dev`** (default department после миграции).

**Выбор:** возвращать `dev` по умолчанию, не 400. Обоснование:

- Сразу после миграции с v1.x **единственный отдел и есть `dev`** — 400 в этом сценарии сломает все клиенты, включая curl-скрипты пользователей. UX-регрессия.
- Owner-факт: «после v2.0 я открываю старый URL и вижу свой dev-канбан, как раньше» — это правильное ощущение upgrade'а.
- Контр-аргумент «400 заставляет клиента явно указать отдел и тем самым воспитывает корректное использование» — справедлив, но мы предпочитаем мягкую миграцию. В логах endpoint'а пишем `WARNING: /api/tasks called without X-Department, defaulting to 'dev'` — этого достаточно, чтобы поймать клиентов, которые забыли проставить header перед удалением fallback'а в v2.1+.
- Если default department `dev` **архивирован** (owner может его удалить через `PATCH /api/departments/dev/archive`), тогда fallback не срабатывает и endpoint возвращает 400 `{"error": "no current department; set X-Department header"}`.

Аналогично — `GET /api/chat`, `GET /api/roles` (старые v1.x endpoints) применяют ту же логику.

#### 2.4.2. Frontend хранит `current_department` в `localStorage`

- Ключ: `devboard:current_department`, значение — `id` отдела.
- При запуске SPA читает localStorage. Если ключа нет — ставит `dev`.
- При переключении отдела в Sidebar — обновляет localStorage **и** Cookie `current_department` (для SSR/server-side фоллбэка).
- При запросах: header `X-Department: <id>` ставится axios/fetch-интерсептором единожды.

### 2.5. UI Sidebar — спецификация

Существующий sidebar дашборда (`dashboard/static/sidebar.js` или эквивалент — точное расположение определит frontend) — навигация по разделам (Канбан / Чат / Роли / Settings). v2.0 добавляет **новую секцию «Departments»** между основной навигацией и футером.

```
┌─────────────────────────────┐
│ Logo / DevBoard             │
├─────────────────────────────┤  ← основная nav
│ ▶ Kanban                    │
│   Chat                      │
│   Roles                     │
│   Settings                  │
├─────────────────────────────┤  ← новая секция «Departments»
│ DEPARTMENTS                 │
│                             │
│ 🛠  Dev          [active]   │  ← подсвечен = current_department
│ 📣  Marketing               │
│ 🎨  Design                  │
│ 💼  Sales                   │
│ ─────────────               │
│ + Department                │  ← кнопка, открывает HR-flow (ADR-004)
├─────────────────────────────┤  ← footer (как было)
│ user@... · v2.0             │
└─────────────────────────────┘
```

Правила:

- **Иконка** = `department.icon` (вычисляется бэкендом по `template_id`, см. §2.3.1).
- **Активный** — подсвечен (CSS-класс `.dept-active`, фон чуть светлее).
- **Архивные** — не показываются по умолчанию; внизу секции ссылка «Show archived (2)», по клику разворачивается список с приглушённым стилем.
- **Клик по отделу** → переключение `current_department` в localStorage + cookie, без перезагрузки страницы (SPA-routing). Все панели (канбан, чат, роли) перерисовываются с новыми данными.
- **`+ Department`** — открывает модалку с HR-диалогом (детали — ADR-004). До завершения HR-сессии новый отдел в списке отображается со статусом `pending`.

## 3. Migration plan

Цель: переход с v1.x БД на v2.0 без потери данных и без даунтайма больше одного рестарта дашборда.

### 3.1. Скрипт `scripts/migrate_v2_departments.py`

Запускается **один раз** при первом старте v2.0 (или вручную). Делает **одну транзакцию**:

```sql
BEGIN TRANSACTION;

-- Шаг 1. Создаём таблицу departments.
CREATE TABLE departments (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  description TEXT NOT NULL DEFAULT '',
  template_id TEXT,
  hr_session_id TEXT,
  created_at INTEGER NOT NULL,
  archived_at INTEGER
);
CREATE INDEX idx_departments_archived ON departments(archived_at) WHERE archived_at IS NULL;

-- Шаг 2. Создаём default department 'dev'.
INSERT INTO departments (id, name, description, template_id, hr_session_id, created_at)
VALUES ('dev', 'Dev', 'Команда разработки devboard (мигрировано с v1.x)', NULL, NULL, strftime('%s','now'));

-- Шаг 3. ALTER на tasks/roles/chat_messages — добавляем nullable department_id.
ALTER TABLE tasks         ADD COLUMN department_id TEXT REFERENCES departments(id);
ALTER TABLE roles         ADD COLUMN department_id TEXT REFERENCES departments(id);
ALTER TABLE chat_messages ADD COLUMN department_id TEXT REFERENCES departments(id);

-- Шаг 4. Backfill всех существующих задач → 'dev'.
UPDATE tasks         SET department_id = 'dev' WHERE department_id IS NULL;

-- Шаг 5. Backfill ролей — все НЕ-глобальные → 'dev'. Глобальные (HR, owner/«пользователь») остаются NULL.
UPDATE roles SET department_id = 'dev'
  WHERE department_id IS NULL
    AND name NOT IN ('hr', 'owner', 'пользователь', 'user');

-- Шаг 6. Backfill чата — все существующие сообщения уходят в 'dev'.
-- (В v1.x чат был один; теперь становится per-dept чатом отдела 'dev'.)
UPDATE chat_messages SET department_id = 'dev' WHERE department_id IS NULL;

-- Шаг 7. Создаём индексы.
CREATE INDEX idx_tasks_department         ON tasks(department_id);
CREATE INDEX idx_tasks_dept_status        ON tasks(department_id, status);
CREATE INDEX idx_roles_department         ON roles(department_id);
CREATE INDEX idx_chat_messages_department ON chat_messages(department_id, created_at DESC);

-- Шаг 8. Сохраняем версию схемы.
INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('version', 'v2.0-departments');

COMMIT;
```

Транзакция атомарна: если любой шаг падает — откатывается всё, БД остаётся на v1.x, дашборд продолжает работать (`migrate_v2_departments.py` фиксирует ошибку в лог, возвращает non-zero, дашборд показывает баннер «migration failed, see logs»).

### 3.2. Pre-flight check

Перед миграцией скрипт проверяет:

1. `schema_meta.version != 'v2.0-departments'` (защита от повторного запуска).
2. Таблицы `tasks`, `roles`, `chat_messages` существуют.
3. Backup создан: `cp devboard.db devboard.db.pre-v2.bak`. Если не получилось — отказ.

### 3.3. Откат

`scripts/migrate_v2_departments.py --rollback` восстанавливает из `.pre-v2.bak` и удаляет `departments`/индексы. Используется, если после миграции владелец решил вернуться на v1.x.

## 4. Consequences

### 4.1. Плюсы

- **Масштабирование команд.** Owner создаёт `Marketing`, `Design`, `Sales` — каждый отдел изолирован, не мешает другому.
- **OSS-приватные форки.** Контрибьютор может форкнуть devboard и собрать свою «AI-консалтинговую фирму» из отделов под клиентов — без правки кода, только через HR-flow.
- **Чистая модель данных.** Каждая задача/роль/сообщение знает свой отдел; запросы фильтруются по индексу, не by `WHERE-NOT-LIKE`-эвристикам.
- **Soft-archive.** Удаление отдела не теряет историю — `archived_at` + partial index дают быстрые «активные отделы» и сохраняют аудит.
- **Backward compatibility.** Legacy endpoints не отменены — старые клиенты v1.x продолжают работать через fallback на `dev`.
- **Аудит cross-task'ов.** `inter-department` channel даёт owner'у единое место, где видно, как отделы перебрасываются задачами (детали — ADR-005).

### 4.2. Минусы / риски

- **Perf под per-department queries.** Без индексов `tasks(department_id, status)` запрос «канбан отдела marketing» — full table scan. Решение — индексы из §2.2 обязательны при миграции, не отложить.
- **Complexity миграции.** Backfill 5 шагами в одной транзакции — если упадёт на середине, нужен корректный откат. Mitigation: §3.2 обязательный backup + §3.3 rollback-скрипт.
- **UI complexity Sidebar.** Owner с 30+ отделами получит длинный sidebar — потребуется scroll/collapse. В v2.0 решается тривиально (CSS overflow), под 100+ отделов нужен virtualized-список — отложено (§6).
- **Header `X-Department` каверы.** Любой клиент API теперь обязан понимать концепт «текущий отдел». Mitigation — fallback на `dev` (§2.4.1) + warning в логах.
- **Cross-department queries сложнее.** «Покажи все задачи всех отделов, где `assignee = qa`» — теперь требует `WHERE department_id IS NOT NULL`, никакого автоматического scope. Решение — отдельная ADR-005 для cross-dept use-cases.
- **`tasks` без `NOT NULL` в SQLite.** SQLite не позволяет добавить `NOT NULL` через `ALTER TABLE`, только через rebuild. Принимаем как есть: enforcement на уровне API (insertion-time check). В новой схеме `tasks` (если её перепишут под другую ADR) — `NOT NULL` ставится сразу.
- **Один HR на инстанс.** Если в крупной OSS-инсталляции захотят разделить «HR для marketing» и «HR для engineering» — придётся ADR-003-rev. Сейчас YAGNI.

## 5. Alternatives Considered

### 5.1. Multi-tenancy через отдельные SQLite файлы

«Каждый отдел = свой `marketing.db`, `design.db`, …». **Отвергнуто.**

- Cross-department аналитика (даже простая: «сколько всего задач в работе») = join по N файлам, сложно и медленно.
- Бэкапы становятся per-file, а не единый snapshot — координация версий между файлами.
- HR (глобальная роль) пишет в `departments`-таблицу, которой в этой схеме нет.
- `inter-department` channel негде хранить.
- Open-source: пользователь захочет переименовать/архивировать отдел — операция над файловой системой, не SQL.

### 5.2. Department-as-label вместо отдельной таблицы

«Не добавляем `departments`-таблицу; вместо неё в `tasks` ставим `label='department:marketing'`». **Отвергнуто.**

- Нет referential integrity — опечатка `department:markting` создаёт «отдел-призрак».
- Негде хранить `template_id`, `hr_session_id`, `archived_at`, `description`.
- Нет уникальности имён.
- Soft-archive отдела невозможен (как «удалить» label, оставив историю?).
- Sidebar строить негде — нужно `SELECT DISTINCT label`-запрос на каждой загрузке.

### 5.3. Global kanban с фильтром по отделу

«Один `/api/tasks` без `department_id`, frontend фильтрует по UI-чекбоксам». **Отложено**, не отвергнуто.

- §1.1 пункт 1: owner работает в контексте одного отдела за раз — глобального view сейчас не хочет.
- Когда понадобится (отдельный ADR) — реализуется поверх per-department схемы: `GET /api/tasks/all` без `department_id`-фильтра. Текущая модель данных это поддержит без миграции, нужны только сами endpoint + UI-toggle. Поэтому решение «отложить» дёшево.

### 5.4. Один общий чат с прозрачным фильтром по отделу

«Чат один, у каждого сообщения `department_id` — frontend фильтрует». **Отвергнуто** для основного use-case.

- Per-department изоляция нужна на уровне scrollback: пользователь, переключившись в `Marketing`, не должен видеть последние 100 сообщений из `Dev`.
- Но **именно эта схема используется** для `inter-department` channel (`department_id IS NULL`) — там нужна сводная видимость cross-task'ов. То есть архитектурно реализация общая (одна таблица `chat_messages` с nullable `department_id`), а UX — два разных канала: per-dept (фильтр по `id`) и global (`IS NULL`).

### 5.5. UUID вместо slug в `departments.id`

См. §2.1.1. **Отвергнуто.** Slug читаемее в URL/header, уникальность гарантирована `PRIMARY KEY`, для multi-tenant SaaS — отдельная ADR при необходимости.

## 6. Open questions

Отложено до отдельных ADR / итераций:

1. **Cross-department queries — отдельный ADR.** Когда `tasks` начнут массово ссылаться друг на друга через границы отделов (`marketing → dev: "помогите со скриптом аналитики"`), потребуются `requester_department_id`, правила видимости, лимиты cross-dept-нагрузки. См. ADR-005 (в работе) — там детали.
2. **Глобальный канбан UX.** §5.3 — отложен. Когда owner попросит — решаем отдельной ADR.
3. **Perf под 100+ отделов.** Текущие индексы рассчитаны на 10–50 отделов. Под 100+ потребуется: партиционирование `chat_messages` по `department_id` (или вынос в отдельные таблицы per-dept), virtualized-Sidebar, ограничение `GET /api/departments` пагинацией. Сейчас YAGNI — owner начинает с 3–5 отделов.
4. **Удаление отдела «насовсем» (hard-delete).** В v2.0 — только soft-archive. Hard-delete (с каскадным удалением tasks/roles/chat) — отдельная операция, требует UX-warning и аудит-логи. Отложено.
5. **HR-multi-instance.** §1.1 пункт 5 — фиксировано: один HR. Если потребуется «HR для marketing» отдельно от «HR для engineering» — ADR-003-rev.
6. **Импорт/экспорт отдела между инстансами.** «Я хочу скачать конфигурацию `Marketing` и перенести в другой инстанс devboard». Сильно завязано на template_id версионирование. Отложено.

## 7. Related ADRs

- **ADR-001** — `docs/adr/0001-llm-provider.md` — `LLMProvider`-абстракция. Роли отдела используют per-role `llm`/`model` из ADR-002, провайдер не знает про отделы (это знает agent-loop).
- **ADR-002** — `docs/adr/0002-role-format.md` — формат `роли/<dept>/<role>.md`. В v2.0 пути роли расширяются префиксом отдела, frontmatter — без изменений. `department_id` хранится в БД (`roles.department_id`), не в frontmatter — чтобы один и тот же файл шаблона `_templates/marketing-v1/copywriter.md` мог инстанцироваться в несколько отделов с разными `department_id`.
- **ADR-004** — `docs/adr/0004-hr-role.md` (пишется параллельно) — workflow создания отдела через HR-pipeline. ADR-003 предоставляет модель данных, ADR-004 — диалоговый flow «HR интервьюирует пользователя → создаёт отдел».
- **ADR-005** — `docs/adr/0005-inter-department.md` (пишется параллельно) — правила cross-department задач. Использует расширение `tasks.requester_department_id` (не описано здесь, см. ADR-005). `inter-department` channel из ADR-003 — место аудита cross-task событий из ADR-005.

## 8. Tasks для backend

Не разворачивать здесь полную реализацию — это работа бэкенда, ниже только заголовки и связи:

1. **B1. Миграция SQLite** — `scripts/migrate_v2_departments.py` (см. §3). Включает: backup, atomic-транзакция, rollback-режим, schema_meta-маркер версии. **Acceptance:** smoke-сценарий из §3.1 на тестовой v1.x БД проходит, `--rollback` восстанавливает исходное состояние.
2. **B2. Модели `Department`** — добавить в `mcp_server/models.py` и `dashboard/db.py` (две точки доступа к БД сейчас — выровнять). Pydantic-модель `Department`, dataclass или ORM-стиль — по выбору бэкенда, главное согласованность с §2.1.
3. **B3. REST endpoints** — `/api/departments/*` из §2.3. Каждый endpoint: handler + sql + JSON-схема ответа + ошибки 4xx (404 отдел не найден, 409 имя занято, 400 невалидный slug).
4. **B4. Middleware `X-Department`** — парсинг header / query / cookie с приоритетом §2.4.1. Подкладывает `request.department_id` в context (Flask `g` или эквивалент). Покрывает legacy-endpoints `/api/tasks`, `/api/chat`, `/api/roles`.
5. **B5. Soft-archive операции** — `PATCH /archive` / `PATCH /unarchive`. При archive все активные HR-сессии этого отдела закрываются (детали — ADR-004).
6. **B6. Inter-department channel endpoint** — `GET /api/chat/inter-department` (фильтр `department_id IS NULL`). Запись в этот канал — из логики ADR-005, не из ADR-003.

## 9. Tasks для frontend

1. **F1. Sidebar widget «Departments»** — секция из §2.5. Получает `GET /api/departments`, рендерит список с иконками и счётчиками. Подсветка active.
2. **F2. localStorage logic `current_department`** — чтение при старте, write на switch, синхронизация с cookie. Дефолт `dev` если ключа нет.
3. **F3. Switching UX без перезагрузки** — клик по отделу в sidebar → обновить state → перерисовать панели (Kanban/Chat/Roles) с новыми данными. Не `window.location.reload()`.
4. **F4. Axios/fetch interceptor для `X-Department`** — единая точка, все API-вызовы автоматически проставляют header из current_department.
5. **F5. Модалка «+ Department»** — кнопка из §2.5. Открывает диалог HR (детали UX — ADR-004), от ADR-003 нужны только: вызов `POST /api/departments` и отображение `status: pending`.
6. **F6. Архивные отделы collapsed-секция** — «Show archived (N)» внизу списка отделов.

## 10. Tasks для QA

1. **Q1. Smoke миграции с v1.x snapshot БД → v2.0.** Подготовить snapshot реальной v1.x БД (с tasks/roles/chat), прогнать `migrate_v2_departments.py`, проверить:
   - `departments` содержит ровно одну запись `id='dev'`.
   - Все `tasks.department_id = 'dev'`.
   - `roles.department_id = 'dev'` для всех ролей, **кроме** HR/owner/«пользователь» — у тех `IS NULL`.
   - `chat_messages.department_id = 'dev'` для всех.
   - `schema_meta.version = 'v2.0-departments'`.
2. **Q2. Cross-department isolation tests.** Создать `marketing` и `design`, проверить:
   - `GET /api/departments/marketing/tasks` возвращает только marketing-задачи.
   - Утилита `copywriter` (роль marketing) не видит роли design в `GET /api/departments/marketing/roles`.
   - `GET /api/departments/design/chat` не возвращает сообщений marketing.
3. **Q3. Legacy compatibility test.** `GET /api/tasks` без `X-Department` после миграции возвращает `dev`-задачи (не 400, не пустой список). Warning есть в логах.
4. **Q4. Archive/unarchive.** Архивированный отдел не появляется в `GET /api/departments` без `?archived=true`. Его задачи остаются доступны через прямой URL `/api/departments/<id>/tasks` (для аудита). Восстановление возвращает в активные.
5. **Q5. Rollback test.** Прогнать миграцию, потом `--rollback`, убедиться что БД бит-в-бит совпадает с `.pre-v2.bak`.

## 11. References

- ADR-001 — `docs/adr/0001-llm-provider.md`
- ADR-002 — `docs/adr/0002-role-format.md`
- ADR-004 (в работе) — `docs/adr/0004-hr-role.md`
- ADR-005 (в работе) — `docs/adr/0005-inter-department.md`
- Текущая схема БД — `mcp_server/db.py`, `dashboard/db.py`
- Sidebar дашборда — `dashboard/static/` (точное расположение — frontend)

## Changelog

- **2026-05-22:** Initial draft (Proposed) — задача `0589d0c031e8` (v2.0/adr).

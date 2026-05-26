# ADR-009 — Управляющий + 11 готовых отделов из knowledge-work-plugins

- **Status:** Proposed (2026-05-25, rev 2 после обсуждения owner-а)
- **Authors:** Claude-сессия (Opus 4.7) совместно с owner'ом
- **Sprint:** TBD (после ревью owner'ом)
- **Supersedes:** —
- **Depends on:**
  - **ADR-003** (`0003-departments.md`) — модель `departments`.
  - **ADR-004** (`0004-hr-role.md`) — HR-pipeline, YAML-шаблоны отделов. HR **остаётся** для нестандартных случаев.
  - **ADR-005** (`0005-inter-department.md`) — cross-department workflow (Lead→Lead, escalation, rate-limit). Управляющий — главный заказчик cross-task.
- **Related:**
  - **ADR-007** (`0007-advisor.md`) — Advisor (внешний советник) живёт **рядом** с Управляющим, не заменяет.
  - **ADR-008** (`0008-channels.md`) — Управляющий шлёт сводки owner'у через Telegram-канал.

---

## TL;DR (для не-программистов)

Сейчас Devboard — это **одна команда разработки** (тимлид + 6 специалистов). Owner общается с тимлидом, тимлид раздаёт работу команде.

После v3.0 будет **компания из отделов** (как настоящий бизнес Acme): маркетинг, продажи, юристы, финансы, дизайн, разработка и т.д. Чтобы owner не общался с 11 тимлидами параллельно — над ними появляется **Управляющий**: один собеседник для owner'а, который раздаёт работу лидам отделов.

**Управляющий — это персональный ассистент** с **долгосрочной памятью** между сессиями. Он помнит стиль owner'а, прошлые решения, специфику компании, паттерны отделов.

**Большинство задач Управляющий распределяет напрямую** в нужный отдел (без обсуждений). **Планёрка** запускается **только когда нужно** — owner попросил, или задача стратегическая. Тогда лиды собираются и **обсуждают между собой** в поисках лучшего решения, выдают список вопросов owner-у, после ответа — стартуют параллельно.

Содержимое отделов (что умеет маркетолог, юрист, финансист) **не пишем с нуля** — берём 11 готовых плагинов от Anthropic (`knowledge-work-plugins`), декомпозируем их универсальных «маркетологов» на нашу модель «лид + специалисты».

Результат — Devboard превращается из узкоспециализированного канбана для AI-разработки в **операционную систему для AI-офиса любой компании**.

---

## 1. Context

### 1.1. Где мы сейчас (v2.1.2)

| Слой | Что есть |
|---|---|
| **Уровень 1**: Owner | owner (или любой owner) — заказчик задач через дашборд (порт 4999). |
| **Уровень 2**: Тимлид | `roles/тимлид.md` (один файл, opus, 34KB). Принимает задачи от owner'а, декомпозирует, делегирует через Task tool. |
| **Уровень 3**: Специалисты | бэкенд / qa / архитектор / frontend / devops / техписатель — 6 файлов в `roles/`. |

Это работает для **одного отдела (dev)**. ADR-003/004/005 спроектировали **multi-department v2.0**, но **не дали ответа на вопрос «с кем owner разговаривает»** когда отделов 11. Default по ADR-003 — owner работает в контексте одного отдела за раз (per-department views). На практике у owner'а часто задачи **многоотдельные**: «лендинг» = маркетинг + разработка + юристы; «выйти на новый рынок» = sales + legal + finance + marketing. Постоянно переключаться между 11 канбанами и говорить с 11 тимлидами — UX-катастрофа.

### 1.2. Что owner сформулировал в обсуждении 2026-05-25

1. **Свой тимлид в каждом отделе** — да, нужно. Один общий «прораб» не понимает специфику маркетинга, юриспруденции и т.д.
2. **Над ними — главный управляющий**, с которым owner общается **в чате дашборда** (заменяет текущий чат с одним тимлидом).
3. Управляющий **видит все отделы**, **знает что они делают**, **ходит по ним**, **ставит задачи их тимлидам**.
4. **Паттерн «планёрка»**: управляющий получает задачу → опрашивает релевантных тимлидов («что вам нужно от owner-а для старта?») → собирает уточняющие вопросы → консолидирует и приносит owner'у → получает ответы → распределяет реальные задачи.
5. **11 отделов = 11 готовых шаблонов** (по аналогии с тем как Anthropic в `knowledge-work-plugins` собрал универсалов для каждого отдела — но мы их **декомпозируем на роли**, чтобы работать параллельно).

### 1.3. Конкретный пример который должен заработать

```
[Owner в чате] Нужен лендинг для outdoor billboards.

[Управляющий] Понял. Это нужно трём отделам: маркетинг, разработка, юристы.
              Запускаю планёрку — соберу уточняющие вопросы.
              [Создаёт planning-задачу в каждом из 3 отделов]

[10 минут позже]

[Управляющий → Owner]
Для запуска нужно ответить на следующее:
  Маркетинг: бюджет, ЦА (B2B/B2C), USP, города размещения, тональность
  Разработка: хостинг (наш VPS или внешний?), нужен ли SEO, какая CRM-интеграция
  Юристы: в каких регионах размещение (у каждого свои требования)

[Owner отвечает одним сообщением]

[Управляющий] Принял. Распределяю задачи. Маркетинг — копирайтер + бренд-менеджер.
              Когда смыслы готовы — cross-task в разработку.
              Юристы стартуют после получения списка регионов.
              Жди статус через 2 часа.
```

---

## 2. Decision

### 2.1. Иерархия — 3 уровня

```
                    Owner
                      ↓ ↑   (общий чат дашборда)
              ┌── Управляющий ──┐
              │   (один на всё)  │
              ↓ ↑               ↓ ↑    (cross-task REST из ADR-005)
   ┌──────────┴──────┐   ┌──────┴──────────┐
   │ marketing-lead  │   │   dev-lead       │  ...11 лидов
   │ + копирайтер    │   │   + бэкенд       │
   │ + бренд-мен.    │   │   + qa           │
   │ + аналитик      │   │   + frontend     │
   │ + SEO           │   │   + devops       │
   └─────────────────┘   └──────────────────┘
```

| Уровень | Кто | Файлы ролей | Модель | С кем общается |
|---|---|---|---|---|
| 1 | **Owner** | — | человек | Управляющий (в чате) |
| 2 | **Управляющий** | `roles/управляющий.md` (новый, global, dept=NULL) | opus | Owner ↔ лиды отделов |
| 3 | **Лид отдела** | `roles/<dept>/lead.md` (11 шт.) | sonnet | Управляющий ↔ свои специалисты |
| 4 | **Специалист** | `roles/<dept>/<slug>.md` (3-7 на отдел) | sonnet/haiku | свой лид, ревью у лида |

### 2.2. Новая роль — `roles/управляющий.md`

**Файл**: `roles/управляющий.md` (глобальная роль, `department_id=NULL` как HR).

**Frontmatter**:
```yaml
---
schema_version: 1
name: managing-director
slug: managing-director
name_ru: Управляющий
name_en: Managing Director
description: |
  Главный собеседник owner'а. Координирует всех лидов отделов.
  Не выполняет задачи — раздаёт. Проводит планёрки.
llm: claude
model: claude-opus-4-7
tools: "*"
temperature: 0.3
max_tokens: 16000
---
```

**Что управляющий делает** (полный системный промт пишется отдельно, здесь — суть):

1. **При старте сессии**:
   - `chat_recent(limit=20)` — что owner писал.
   - `list_all_inboxes()` (новый MCP-tool, см. §2.6) — общий обзор всех 11 отделов: сколько `wip`, сколько `review`, сколько `blocked`.
   - Если есть новое сообщение owner'а без ответа → ответить.

2. **При получении новой задачи от owner'а — два сценария**:

   **Default flow (без планёрки) — БОЛЬШИНСТВО задач:**
   - Анализ затронутых отделов по ключевым словам / явному указанию.
   - Если задача очевидно scoped в один отдел («перепиши этот пост», «пофиксь баг») — **сразу** создать cross-task через REST (ADR-005) в этот отдел. Не дёргать лида с планировочным вопросом.
   - Если задача очевидно multi-dept, но конкретика ясна («лендинг с готовым ТЗ») — **сразу** создать N cross-task в каждый отдел с правильным контекстом.
   - В обоих случаях — короткий ответ owner-у в чате: «Принял. Поставил задачи в [marketing], [dev]. Жди обновлений».

   **Planning flow (планёрка) — только когда:**
   - Owner явно указал в сообщении: «нужна планёрка перед запуском» или поставил label `planning-required`.
   - Задача стратегическая / большая / неоднозначная — управляющий **сам инициирует** планёрку с уведомлением owner'у («Это большая задача, запускаю планёрку с лидами»).
   - Полный workflow планёрки — §2.4. Суть: совещание руководителей отделов между собой → консолидация вопросов → owner отвечает → распределение.

3. **Между планёрками**:
   - Раз в N минут (через job или сам по запросу) собирать `list_all_inboxes()` и реагировать на:
     - Тимлид перешёл в `blocked` — почему? Помочь разрулить (другой отдел? уточнение owner-у?).
     - Тимлид `review` готов и owner не среагировал >1 часа → уведомить owner-а в чате/Telegram.
     - Cross-task застрял в `needs_approval` → напомнить owner-у.

4. **Не делает работу сам**. Не пишет код, тексты, не редактирует файлы (кроме своих заметок в `advisor_memory` если интегрирован с ADR-007).

5. **Завершение сессии**: `chat_post` в общий чат с итогом — что в работе, что ждёт owner'а, статус планёрок.

**Tools которые управляющий использует**:

| Tool | Зачем |
|---|---|
| `chat_recent(department_id=?)` | мониторинг чатов отделов и общего |
| `chat_post(author='Управляющий', department_id=?)` | коммуникация (планёрки + ответы owner-у) |
| `list_all_inboxes()` (новый) | агрегированный обзор всех 11 отделов |
| `list_departments()` | какие отделы существуют (включая archived) |
| `get_department(<id>)` | детали отдела (роли, capacity) |
| `list_tasks(department_id=?, status=?)` | мониторинг |
| **cross-task REST** `POST /api/departments/<X>/tasks` | создание задач для лидов отделов (с `requester_role_slug='managing-director'`) |
| `notify_user(text, level)` | пинги в Telegram через ADR-008 |

**Tools которые управляющий НЕ использует**:

- `Task tool` (Claude subagent) — он не работает в роли «специалиста», для него subagent'ы не нужны.
- `Read/Write/Edit/Bash` — не пишет код и не правит файлы.
- Прямой `mcp__devboard-tasks__create_task` с чужим department — это идёт через REST (см. ADR-005).

### 2.3. Лиды отделов — `roles/<dept>/lead.md` (11 файлов)

Каждый отдел получает **свой файл lead'а**. Слаги ролей и slug файлов:

| dept | Lead роль (slug) | Файл |
|---|---|---|
| dev | `dev-lead` (текущий тимлид переименовывается!) | `roles/dev/lead.md` |
| marketing | `marketing-lead` | `roles/marketing/lead.md` |
| sales | `sales-lead` | `roles/sales/lead.md` |
| legal | `legal-lead` | `roles/legal/lead.md` |
| finance | `finance-lead` | `roles/finance/lead.md` |
| customer-support | `support-lead` | `roles/customer-support/lead.md` |
| product-management | `pm-lead` | `roles/product-management/lead.md` |
| design | `design-lead` | `roles/design/lead.md` |
| data | `data-lead` | `roles/data/lead.md` |
| operations | `ops-lead` | `roles/operations/lead.md` |
| human-resources | `hr-lead` (НЕ путать с глобальным `hr` — это другой!) | `roles/human-resources/lead.md` |

**Текущий `roles/тимлид.md` становится `roles/dev/lead.md`** при миграции. Полная инструкция (CHECKLIST, safety-net, коммуникационная дисциплина) сохраняется — она универсальна для лидов.

**Общая база у всех лидов** (вынести в `roles/_common/lead-base.md` и инклюдить — см. Open Question 6.4):

- Декомпозиция задач на подзадачи специалистам своего отдела.
- Делегирование через Task tool параллельно.
- Safety-net (не ставить done, обязательный CHECKLIST перед `chat_post`).
- Cross-task в другие отделы через REST (только Lead может — это уже в ADR-005).
- Коммуникационная дисциплина (один факт — одно место).

**Специфика каждого лида**:

- Список своих специалистов (например marketing-lead знает что у него копирайтер, бренд-менеджер, аналитик).
- Доменные фреймворки (как маркетинг-лид думает о кампаниях, как legal-лид о рисках).
- Output specs (что отдел производит — landing-копия, NDA-чек, ROI-репорт).

**Модель**: `claude-sonnet-4-6` (не opus). Координация внутри одного отдела проще общей координации; sonnet справится. Это **критичная экономия токенов** — opus у 11 лидов был бы по $5+/session.

### 2.4. Паттерн «Планёрка» — opt-in workflow

**Планёрка — НЕ default**. Используется только когда owner явно её попросил (`label='planning-required'` или текст «нужна планёрка») или управляющий сам решил что задача требует обсуждения лидов (стратегическая / большая / неоднозначная).

**Концепция**: это **совещание руководителей отделов в поисках наилучшего решения** + **сбор уточняющих вопросов** для owner-а. Лиды отделов **обсуждают между собой**, а не просто параллельно отвечают.

```
                     ┌─────────────────┐
                     │  owner: запрос  │
                     │  (+ флаг        │
                     │  planning-req)  │
                     └────────┬────────┘
                              ↓
            ┌──── Phase 1: Созыв совещания ──┐
            │  Управляющий создаёт           │
            │  planning_session,             │
            │  пишет в чаты N отделов        │
            │  «Зову на совещание по теме X. │
            │  Контекст: <...>»              │
            └────────┬───────────────────────┘
                     ↓
       ┌──── Phase 2: Обсуждение ───────────────┐
       │  Лиды отделов пишут в shared          │
       │  planning-канал. Видят ответы друг    │
       │  друга. Обсуждают подходы, риски,     │
       │  зависимости. 1-3 раунда обмена.      │
       │  Управляющий модерирует.              │
       └────────┬──────────────────────────────┘
                ↓
       ┌──── Phase 3: Консолидация ────────────┐
       │  Управляющий синтезирует:             │
       │  - Предлагаемое решение               │
       │  - Список вопросов для owner-а        │
       │    (что нужно прояснить)              │
       │  Пишет owner-у в общий чат.           │
       └────────┬──────────────────────────────┘
                ↓
          [owner отвечает]
                ↓
       ┌──── Phase 4: Распределение ───────────┐
       │  Управляющий → cross-task REST        │
       │  в каждый отдел с полным контекстом   │
       │  + ссылкой на planning_session_id     │
       └────────────────────────────────────────┘
```

**Ключевое отличие от default flow**: в Phase 2 **лиды видят ответы друг друга**. Это значит когда `marketing-lead` пишет «нам нужно понять ЦА», а `dev-lead` пишет «нам нужен deploy target» — каждый из них **видит вопросы другого** и может среагировать: «marketing — если ЦА B2B, то deploy на корпоративном поддомене».

**Хранение состояния планёрки** — в БД новая таблица:

```sql
CREATE TABLE planning_sessions (
  id           TEXT PRIMARY KEY,              -- uuid
  owner_request TEXT NOT NULL,                -- исходное сообщение owner'а
  phase        TEXT NOT NULL,                 -- 'gathering' | 'discussion' | 'consolidation' | 'distribution' | 'done'
  departments_involved TEXT NOT NULL,         -- JSON array of dept ids
  discussion_log TEXT,                        -- JSON: [{author, role, text, timestamp}] — обмен лидов между собой
  consolidated_proposal TEXT,                 -- предлагаемое решение которое управляющий собрал
  questions_for_owner TEXT,                   -- список вопросов owner-у
  owner_answer TEXT,                          -- ответ owner-а
  created_tasks TEXT,                         -- JSON: [{dept, task_id}, ...]
  started_at   INTEGER NOT NULL,
  finished_at  INTEGER
);

CREATE INDEX idx_planning_phase ON planning_sessions(phase) WHERE finished_at IS NULL;
```

**UI индикатор**: в шапке общего чата (если есть активные planning_sessions) — пометка `🤔 Планёрка идёт: маркетинг, разработка, юристы (Phase 2 — обсуждение, 4 реплики)`. Клик → раскрывается панель с полным `discussion_log` (лиды видят друг друга в реальном времени).

**Re-entry policy** (вместо тайминговых timeout'ов): планёрка — асинхронный процесс между Claude-сессиями. При каждом следующем запуске управляющего:
- Проверяет активные planning_sessions (`phase != 'done'`).
- Для каждой смотрит — кто из лидов ещё не дал реплики на текущем раунде. Пишет им повторно в чат отдела с напоминанием.
- Если лид не ответил **3 раза подряд** (счётчик в `discussion_log`) — управляющий эскалирует owner-у: «отдел X молчит, продолжаем без них или отложить задачу?».

### 2.5. Декомпозиция 11 плагинов в наши шаблоны

**Источник**: `vendored/knowledge-work-plugins/` (git submodule или копия — см. Open Question 6.5).

**Целевое расположение**:
- YAML-шаблоны (ADR-004 формат): `templates/departments/<dept>-v2.yaml`
- Файлы ролей: `roles/<dept>/<slug>.md`

**Принцип декомпозиции**: каждый skill из knowledge-work-plugin (например `marketing/skills/brand-review/SKILL.md`) ложится в **output_spec** соответствующей роли, а workflow из SKILL.md — в **system_prompt_template** роли.

**Пример: marketing-v2** (источник — `vendored/knowledge-work-plugins/marketing/skills/`, 8 скиллов):

```yaml
id: marketing-v2
name: Marketing
name_en: Marketing
description: Контент, кампании, бренд, аналитика
icon: 📣
mcp_connectors: [slack, hubspot, notion, ahrefs, klaviyo]  # из vendored .mcp.json
roles:
  - slug: marketing-lead
    name_ru: Маркетинг-лид
    name_en: Marketing Lead
    model: claude-sonnet-4-6
    is_lead: true
    skills: [strategy, planning, briefing, competitive-analysis]
    inherits_skills: [campaign-plan, competitive-brief]  # 2 скилла из 8
    output_spec: |
      Координирует команду. Планирует кампании. Конкурентный анализ.
      Output: campaign brief, weekly plan, competitive battlecard.

  - slug: copywriter
    name_ru: Копирайтер
    name_en: Copywriter
    model: claude-sonnet-4-6
    skills: [writing, editing, seo-light]
    inherits_skills: [draft-content, email-sequence]  # 2 скилла
    output_spec: |
      Пишет посты, email, лендинги, пресс-релизы, кейсы.
      Output: markdown drafts (1-3 per task), reviewed by marketing-lead.

  - slug: brand-manager
    name_ru: Бренд-менеджер
    name_en: Brand Manager
    model: claude-sonnet-4-6
    skills: [brand, voice, terminology]
    inherits_skills: [brand-review]  # 1 скилл
    output_spec: |
      Проверка контента на соответствие бренду.
      Output: brand-review report с severity-уровнями и предложениями.

  - slug: marketing-analyst
    name_ru: Маркетинг-аналитик
    name_en: Marketing Analyst
    model: claude-sonnet-4-6
    skills: [analytics, reporting, attribution]
    inherits_skills: [performance-report]  # 1 скилл
    output_spec: |
      Отчёты по эффективности, метрики, оптимизация воронок.
      Output: performance report (markdown + tables), recommendations.

  - slug: seo-specialist
    name_ru: SEO-специалист
    name_en: SEO Specialist
    model: claude-sonnet-4-6
    skills: [seo, keyword-research, technical-seo]
    inherits_skills: [seo-audit]  # 1 скилл
    output_spec: |
      SEO-аудиты, ключевые слова, технический SEO, content gaps.
      Output: SEO audit report, keyword strategy.
```

**Итого**: 8 скиллов knowledge-work-plugins/marketing → **5 ролей** в нашем формате. Каждая роль наследует 1-2 скилла как `inherits_skills` (это новое поле в YAML — оно говорит «загрузи `vendored/knowledge-work-plugins/marketing/skills/<skill>/SKILL.md` как часть system_prompt_template этой роли»).

**Аналогично делаются 10 других отделов**. Примерные декомпозиции (детальные YAML — отдельные задачи backend'у на реализацию):

| dept | Скиллов в плагине | Ролей в нашем формате |
|---|---|---|
| sales | 9 | 4 (sales-lead + prospect-researcher + outreach-writer + battlecard-specialist) |
| legal | 9 | 4 (legal-lead + contract-reviewer + compliance + research) |
| finance | 8 | 4 (finance-lead + accountant + analyst + audit-support) |
| customer-support | 5 | 3 (support-lead + responder + kb-writer) |
| product-management | 8 | 4 (pm-lead + research-synthesizer + spec-writer + roadmap-keeper) |
| engineering | 10 | 6 (dev-lead + бэкенд + qa + frontend + devops + архитектор — **наш текущий состав!**) |
| human-resources | 9 | 4 (hr-lead + recruiter + onboarder + people-analyst) |
| design | 7 | 4 (design-lead + ux-researcher + visual-designer + accessibility-reviewer) |
| data | 10 | 5 (data-lead + sql-writer + visualizer + statistician + validator) |
| operations | 9 | 4 (ops-lead + process-doc-writer + risk-assessor + compliance-tracker) |

**Замечание про engineering**: это **уже наш текущий dev-отдел**. Декомпозиция knowledge-work-plugins/engineering на 6 ролей ≈ наш текущий состав. Это значит:
1. После принятия ADR-009 наш `dev` department становится первым «правильно декомпозированным».
2. Можно использовать его как **reference implementation** для остальных 10.

### 2.6. Новые MCP-tools для управляющего

Добавляются в `mcp_server/pride_tasks/tools.py`:

| Tool | Назначение |
|---|---|
| `list_all_inboxes()` | Агрегат по всем отделам: `[{dept_id, dept_name, wip_count, review_count, blocked_count, last_chat_msg_time}, ...]`. Используется управляющим для обзора. |
| `start_planning_session(owner_request, departments)` | Создаёт `planning_sessions` запись в Phase 1, отправляет `chat_post` в каждый затронутый отдел с questioner-text. |
| `collect_planning_responses(planning_session_id)` | Читает chat_recent каждого отдела с метки начала планёрки, парсит ответы тимлидов. Возвращает `{<dept>: [...questions]}`. |
| `finalize_planning_session(planning_session_id, owner_answer)` | Phase 3 — создаёт cross-task в каждом отделе с полным контекстом. Меняет `planning_sessions.phase = 'done'`. |

**Все эти 4 tool'а — только для роли `managing-director`** (проверка role.name на стороне MCP-сервера). Лиды и специалисты их не вызывают.

### 2.6.1. Долгосрочная память Управляющего

**Управляющий = координация + долгосрочная память.** Это объединение того, что в первоначальном плане было разделено (Advisor отдельно, Управляющий отдельно). Owner решил: помнить долгосрочно должен тот, с кем он постоянно общается.

**Что помнит Управляющий между сессиями:**

- **Стиль и предпочтения owner-а** («owner не любит длинные сводки», «использует Markdown-таблицы охотно», «предпочитает решения с тредоффами»).
- **Решения по архитектуре** («2026-05-25 договорились: трёхуровневая иерархия», «отказались от submodule в пользу copy»).
- **Контекст владельца** (продукты, клиенты, ключевые сделки, специфика производства наружной рекламы).
- **Прошлые планёрки** — какие задачи обсуждались, к каким выводам пришли, что не получилось.
- **Паттерны отделов** — какой лид обычно тянет дольше, какой отдел часто блокируется, у какого лида хорошие предложения.

**Технический дизайн памяти**: см. **ADR-007** (`0007-memory-layer.md`, переименован из «Advisor»). Там описаны:
- SQL-схема `manager_chunks` + FTS5.
- 5 MCP-tools: `manager_memory_add/search/get/recent/archive`.
- Bootstrap-режим контекста (загружать всё нужное один раз в начале сессии).

**Управляющий при каждом старте сессии**:
1. `chat_recent(limit=20)`.
2. `list_all_inboxes()`.
3. `manager_memory_recent(source='note', limit=20)` — структурные факты.
4. `manager_memory_search(<тема последнего сообщения owner-а>)` — релевантные воспоминания.

**При значимом выводе**:
- `manager_memory_add(source='recall', ...)` — записать, чтобы в следующей сессии помнить.

Это **превращает Управляющего из stateless-роли в персонального ассистента** с памятью между сессиями.

### 2.7. UI изменения

#### 2.7.1. Кнопка «+ Department» — новый список

Сейчас в Sidebar (ADR-003 §2.5) есть кнопка `+ Department` которая открывает HR-диалог. После ADR-009 она открывает **гибридный экран**:

```
┌────────────────────────────────────┐
│  Добавить отдел                    │
├────────────────────────────────────┤
│  🚀 Готовые шаблоны:               │
│                                    │
│  📣 Marketing                      │
│  🤝 Sales                          │
│  ⚖️ Legal                          │
│  💰 Finance                        │
│  🎧 Customer Support               │
│  📦 Product Management             │
│  💻 Engineering                    │
│  👥 Human Resources                │
│  🎨 Design                         │
│  📊 Data                           │
│  ⚙️ Operations                     │
│                                    │
│  ──────────────                    │
│  🧑‍💼 Создать через HR (custom)    │
└────────────────────────────────────┘
```

Клик на готовый шаблон → endpoint `POST /api/departments` с `template_id=<dept>-v2` → отдел создаётся **немедленно** (без HR-диалога), потому что шаблон уже content-полный.

«Создать через HR» — старый ADR-004 pipeline для нестандартных отделов.

#### 2.7.2. Чат дашборда — собеседник теперь Управляющий

Раньше: общий чат → отвечает тимлид (`author='тимлид'`).
Теперь: общий чат → отвечает Управляющий (`author='Управляющий'`). Тимлиды отвечают в чатах своих отделов (`department_id=<X>`).

В Sidebar — глобальный «🏛 Управляющий» (всегда первый, выше списка отделов). Под ним — список отделов.

#### 2.7.3. Индикатор планёрки

В шапке чата, если есть активные planning_sessions:

```
🤔 Планёрка идёт: marketing, dev, legal (Phase 1 — опрос)
   Ответили: 2 из 3. Жду dev-lead.
```

При клике → разворачивается панель с детальным статусом каждой планёрки.

---

## 3. Implementation Plan

### Фаза 1 — Управляющий поверх существующего dev (1 спринт)

| # | Задача | Owner | Сложность |
|---|---|---|---|
| 1 | `roles/управляющий.md` — системный промт (с описанием default/planning flow + памяти) | архитектор + техписатель | Medium (~400 строк) |
| 2 | Переименовать `roles/тимлид.md` → `roles/dev/lead.md` | техписатель | Trivial (mv + update refs) |
| 3 | 4 новых planning MCP-tools (list_all_inboxes, start_planning_session, ...) | бэкенд | Medium (~250 LoC) |
| 4 | 5 memory MCP-tools (`manager_memory_*`) — из ADR-007 | бэкенд | Medium (~200 LoC) |
| 5 | `planning_sessions` + `manager_chunks` + FTS5 таблицы | бэкенд | Easy (~80 LoC) |
| 6 | UI: chat-собеседник теперь Управляющий, dev-lead общается в чате dev | frontend | Easy (~80 LoC JS) |
| 7 | UI: индикатор «🤔 Планёрка идёт» + панель `discussion_log` | frontend | Medium (~150 LoC JS) |
| 8 | E2E test: owner → планёрка для dev → распределение + проверка памяти | qa | Medium (~250 LoC) |

**Acceptance**: тот же сценарий что и сегодня (dev-задачи) — owner пишет «сделай X», управляющий запускает планёрку с dev-lead'ом, dev-lead отвечает что нужно, owner отвечает, задача создаётся в dev-канбане. Без новых отделов.

### Фаза 2 — Один пилотный отдел (marketing) (1 спринт)

| # | Задача | Сложность |
|---|---|---|
| 1 | Vendored knowledge-work-plugins (submodule или copy) | Trivial |
| 2 | `templates/departments/marketing-v2.yaml` — детальная декомпозиция (см. §2.5) | Medium |
| 3 | 5 файлов ролей `roles/marketing/{lead,copywriter,brand-manager,marketing-analyst,seo-specialist}.md` | Medium |
| 4 | `inherits_skills` mechanism — при `create_department` HR-bypass подгружает контент скиллов из vendored | Medium |
| 5 | UI: добавить marketing как готовый шаблон в кнопку «+ Department» | Easy |
| 6 | E2E: создание marketing-отдела, простая задача «напиши пост про новую линейку» | Medium |

**Acceptance**: owner создаёт marketing-отдел одним кликом, ставит задачу через управляющего, видит как 2-3 специалиста параллельно работают, получает результат.

### Фаза 3 — Остальные 10 отделов (2-3 спринта)

После доказательства концепции на marketing — повторить декомпозицию для остальных 10. Каждый отдел = 1 PR.

**Engineering** делаем последним (или первым после Фазы 1?) — потому что это **наш текущий dev**, нужна аккуратная миграция роли `tеамлид → dev-lead` + проверка что safety-net не сломался.

### Фаза 4 — Telegram-сводки от Управляющего (опционально, после ADR-008)

Управляющий шлёт через TG-канал (ADR-008) утренние/вечерние сводки: «сегодня в работе 5 кампаний, 2 контракта на ревью, 3 задачи требуют твоего одобрения».

---

## 4. Consequences

### Плюсы

- **Масштабируемость**. После ADR-009 owner может вести **компанию из 11 AI-отделов** через одну точку контакта.
- **Готовый контент.** 11 отделов из knowledge-work-plugins — содержательно проработаны Anthropic, не нужно писать промты с нуля.
- **Параллельность сохраняется.** Внутри каждого отдела специалисты работают параллельно через Task tool — наша текущая сильная сторона.
- **Чёткие роли.** Owner общается только с Управляющим. Лиды коммуницируют с Управляющим. Специалисты — только с лидом. Это **естественная иерархия** известная любому директору.
- **Reuse существующей инфраструктуры.** ADR-003 (departments), ADR-004 (HR — остаётся для custom-отделов), ADR-005 (cross-task) — всё работает без переделок.
- **Управляющий заменяет один файл `тимлид.md`** — не добавляется хаос с двумя глобальными ролями.

### Минусы / риски

- **Лишний слой → токены.** Каждая задача проходит через дополнительную пару turn'ов (owner ↔ Управляющий ↔ Lead). Оценка: +20-30% input tokens на координацию. **Mitigation:** ADR-006 prompt caching + bootstrap режим (ADR-007 §2.4) для Управляющего.
- **Latency.** Планёрка занимает 5-15 минут (управляющий ждёт ответов тимлидов). Это **не моментальный** ответ owner-у как раньше. **Mitigation:** для простых задач — управляющий может пропустить планёрку (см. Open Question 6.1).
- **Сложность miграции `тимлид → dev-lead`.** Текущий `roles/тимлид.md` содержит 380 строк специфичной логики (safety-net, чек-листы, dev-команда). Перенос требует аккуратности.
- **`hr-lead` ≠ `hr` global** — путаница в названиях. `hr` — глобальная роль ADR-004 которая создаёт **custom** отделы (по диалогу с owner-ом). `hr-lead` — лид отдела HR (рекрутинг, оффер-леттеры). Mitigation: документация + переименование `hr` → `hr-coordinator` (но это breaking change).
- **Vendored 12MB.** Если git submodule — пользователю нужен `--recurse-submodules` при клоне. Если copy — теряем простые обновления от Anthropic.

---

## 5. Alternatives Considered

### 5.1. Один тимлид на все 11 отделов

«Просто расширить `roles/тимлид.md` чтобы он знал про маркетинг, продажи, юристов». **Отвергнуто:**
- Системный промт уже 34KB. Добавление 10 доменов → 200KB+ → context overflow.
- Один тимлид принимает все задачи через одну очередь — нет per-department контекста.
- Сложность мониторинга — owner всё ещё не знает что в каком отделе.

### 5.2. Без управляющего — owner общается с 11 тимлидами напрямую

Per-department views из ADR-003 уже это поддерживают (`current_department` в localStorage). **Отвергнуто owner'ом** в обсуждении 2026-05-25 — он хочет **единого собеседника**.

### 5.3. Использовать knowledge-work-plugins as-is

Подключить их 11 плагинов через стандартный Claude Code mechanism, без декомпозиции на роли. **Отвергнуто:**
- Их формат — один универсал-Claude на отдел. **Нет parallel multi-agent** — основная сильная сторона Devboard теряется.
- Нет канбана и orchestration — для домашнего пользователя ок, для бизнеса — нет.
- Owner Devboard'а не получает преимуществ дашборда.

### 5.4. Двухуровневая иерархия (управляющий заменяет тимлида)

Управляющий **одновременно** делает координацию между отделами **и** декомпозицию внутри них. Без отдельных лидов. **Отвергнуто:**
- Управляющий должен знать **все 11 доменов** — невозможно качественно.
- 1 файл = 200KB+ промта.
- Параллельность внутри отделов теряется (один Claude не может одновременно держать марк-роль и dev-роль).

### 5.5. Manager-of-managers рекурсивно (3+ уровня внутри отделов)

Из openclaw VISION.md (`What We Will Not Merge`): «Agent-hierarchy frameworks (manager-of-managers / nested planner trees) as a default architecture». **Отвергнуто** — для нашего масштаба 3 уровней достаточно. Внутри отдела лид раздаёт **специалистам напрямую** через Task tool, без подмаршалов.

### 5.6. Не делать декомпозицию — оставить knowledge-work-plugins универсалами + добавить только управляющего

«Сделать только новый управляющий и одиночные универсалы вместо отделов». **Отвергнуто:**
- Параллельность внутри отдела теряется.
- Уже наша dev-команда работает по модели декомпозиции — это **наша identity**.
- Owner явно сказал «декомпозируем по аналогии с уже работающим отделом разработки».

---

## 6. Resolved Decisions (2026-05-25)

Все вопросы первой итерации ADR-009 закрыты owner'ом в обсуждении того же дня.

### 6.1. Когда управляющий пропускает планёрку? — **Resolved**

**Default = без планёрки**. Управляющий распределяет задачи напрямую в отделы. Планёрка включается **только** если:
- Owner явно указал в сообщении («нужна планёрка», или label `planning-required`).
- Управляющий сам решил что задача стратегическая / большая / неоднозначная — и **уведомил owner-а** «Это большая задача, запускаю планёрку с лидами» (опционально, см. правила в `roles/управляющий.md`).

Тривиальные задачи («перепиши пост», «пофиксь баг») — **напрямую в доску** соответствующего отдела. Никаких опросов лидов.

Бриф планёрки: «совещание руководителей в поисках наилучшего решения + сбор уточняющих вопросов для owner-а». Подробности — §2.4.

### 6.2. Advisor + Управляющий — **Resolved: объединены**

Изначально планировалось две роли — Управляющий (координация) и Advisor (стратегический советник с долгосрочной памятью). **Owner решил объединить**: долгосрочная память вешается на Управляющего.

Логика: «помнить должен тот с кем я постоянно общаюсь».

- Управляющий = координатор + долгосрочная память (см. §2.6.1).
- ADR-007 переименован: «Advisor» → «Long-term memory layer». Технический дизайн (chunked + FTS5 + MCP-tools) переиспользуется как подсистема Управляющего.
- Отдельной роли «Advisor», вкладки `/advisor`, файла `roles/advisor.md` — **не будет**.

### 6.3. Re-entry policy для лидов — **Resolved (тайминги убраны)**

Идея «30 минут / 60 минут timeout» — артефакт неправильной модели времени в первой редакции. В Claude нет блокирующего ожидания: сессия запустилась → отработала → завершилась. Между сессиями проходит реальное календарное время.

**Правильная модель** (см. §2.4 «Re-entry policy»):
- При каждом следующем запуске Управляющий смотрит активные planning_sessions.
- Кто из лидов не ответил на текущем раунде — повторное приглашение.
- 3 раза подряд молчит — эскалация owner-у в чат: «отдел X не отвечает, продолжаем без них или отложить?».

Без конкретных минут — Управляющий не блокируется, просто проверяет состояние при каждом старте.

### 6.4. `roles/_common/lead-base.md` — **Resolved: да, делаем**

Общая база (safety-net, CHECKLIST, коммуникационная дисциплина) выносится в `roles/_common/lead-base.md`. Каждый из 11 `roles/<dept>/lead.md` включает её через Mustache partial `{{> _common/lead-base.md}}` в YAML-шаблоне.

### 6.5. Vendored knowledge-work-plugins — **Resolved: copy, НЕ submodule**

Копируем папку как обычные файлы в `vendored/knowledge-work-plugins/`. Без git-submodule. Плюс — пользователь не возится с `--recurse-submodules`. Минус — обновления от Anthropic не автоматические; делаем по запросу скриптом `scripts/update_vendored_plugins.sh`.

### 6.6. Модели — **Resolved**

- **Управляющий** — `claude-opus-4-7`.
- **Новые 10 лидов отделов** (всё кроме dev) — `claude-sonnet-4-6`.
- **Новые специалисты** (всё кроме dev) — `claude-sonnet-4-6`.
- **dev-отдел** — **остаётся без изменений**. Текущее распределение моделей (opus для тимлида, sonnet для бэкенда/qa/frontend, и т.д. — см. frontmatter в `roles/`) сохраняется как есть. Только переименование `тимлид.md → dev/lead.md`.

### 6.7. Не-классические плагины — **Resolved: не берём**

Из 14 плагинов в knowledge-work-plugins **не используем**:
- `productivity` (для одного пользователя, не отдел).
- `enterprise-search` (сервис, не отдел).
- `bio-research` (узкоспециализирован — генетика/биология).
- `cowork-plugin-management` (служебный, не функциональный).

Берём ровно **11 классических бизнес-отделов**: marketing, sales, legal, finance, customer-support, product-management, engineering, human-resources, design, data, operations.

### 6.8. Channels (ADR-008) — **Resolved: после, не до**

Сначала строим отделы (ADR-009), потом возвращаемся к коннекторам (ADR-008). ADR-008 переходит в статус **«отложен до завершения ADR-009»**. Telegram-нотификации от Управляющего, Bitrix24-интеграция и т.д. — следующий цикл.

---

## 6a. Действительно открытые вопросы (после Resolved)

1. **Конкретный список вопросов из планёрки — формат**. Должен быть жёстко структурированный JSON в `questions_for_owner` или свободный markdown? Решаем при реализации `finalize_planning_session`.
2. **Кто триггерит «управляющий сам инициирует планёрку»?** Это эвристика в его роли (по размеру/неоднозначности задачи) или формальный label? Уточним в `roles/управляющий.md`.
3. **Стоимость opus-Управляющего в реальной нагрузке**. Замер после Фазы 1.

---

## 7. Related ADRs

- **ADR-003** — `departments` table. ADR-009 использует её без изменений.
- **ADR-004** — HR-pipeline. **HR остаётся** для custom-отделов. ADR-009 добавляет fast-path «11 готовых шаблонов» как альтернативу HR-flow.
- **ADR-005** — Inter-department workflow. ADR-009 расширяет: Управляющий = `requester_role_slug='managing-director'`, имеет право cross-task без явного `requester_department_id` (он не отдел).
- **ADR-007** — Advisor. ADR-009 определяет их разные роли (см. Open Question 6.2).
- **ADR-008** — Channels. Управляющий — главный потребитель TG-канала.

---

## 8. Tasks для backend

1. **B1. Migration** — таблица `planning_sessions` + индексы.
2. **B2. 4 новых MCP-tools** — `list_all_inboxes`, `start_planning_session`, `collect_planning_responses`, `finalize_planning_session`. С проверкой role.name на стороне сервера.
3. **B3. `requester_role_slug='managing-director'`** — расширение ADR-005 cross-task валидации: разрешаем как валидный requester без `requester_department_id`.
4. **B4. `template_id='<dept>-v2'`** — endpoint `POST /api/departments` с этим template_id применяет шаблон **мгновенно** (без HR), копирует роли из YAML в БД.
5. **B5. `inherits_skills` mechanism** — при создании отдела из v2-шаблона читать `vendored/knowledge-work-plugins/<dept>/skills/<skill>/SKILL.md` и инжектить в system_prompt роли.
6. **B6. Migration `тимлид.md → dev/lead.md`** — переименовать файл, обновить refs в `commands/devboard-work.sh`, в БД в `roles` таблице.

## 9. Tasks для frontend

1. **F1. Кнопка «+ Department» — новый экран** с 11 шаблонами + опция «через HR».
2. **F2. Sidebar «🏛 Управляющий»** — глобальный собеседник в общем чате.
3. **F3. Per-department чаты** — каждый отдел имеет свой канал; лид общается в своём канале.
4. **F4. Индикатор планёрки** в шапке общего чата.
5. **F5. Panel «🤔 Планёрки»** — раскрывающаяся панель со списком активных planning_sessions, статусами Phase 1/2/3.

## 10. Tasks для DevOps

1. **D1. Copy `vendored/knowledge-work-plugins/`** — `git clone --depth 1 https://github.com/anthropics/knowledge-work-plugins /tmp/kwp && rm -rf /tmp/kwp/.git && mv /tmp/kwp vendored/knowledge-work-plugins`. Закоммитить в наш репо. Удалить из `vendored/` ненужные плагины: `productivity`, `enterprise-search`, `bio-research`, `cowork-plugin-management` (см. §6.7). Оставить 11 классических.
2. **D2. `scripts/update_vendored_plugins.sh`** — скрипт ручного обновления: тот же clone + diff с текущим + интерактивный prompt «применить?».
3. **D3. `.gitattributes`** для `vendored/` — пометить как vendored (для GitHub language stats: `linguist-vendored=true`).

## 11. Tasks для QA

1. **Q1. Unit-tests** для 4 новых MCP-tools.
2. **Q2. E2E планёрка** — owner ставит multi-dept задачу → Управляющий проходит 3 фазы → задачи появляются в каждом отделе с правильным `requester_role_slug`.
3. **Q3. Skill-inheritance test** — при создании marketing-отдела роль `brand-manager` получает в system_prompt контент `brand-review/SKILL.md`.
4. **Q4. Migration regression** — старые dev-задачи продолжают работать после переименования `тимлид → dev-lead`.
5. **Q5. Timeout test** — лид отдела не отвечает в Phase 1 → управляющий эскалирует owner'у через 60 минут.

## 12. Tasks для архитектора + техписателя

1. **A1. `roles/управляющий.md`** — детальный системный промт:
   - Default flow vs Planning flow (когда что используется).
   - 4 фазы планёрки (gathering → discussion → consolidation → distribution).
   - Re-entry policy (3 раза молчит — эскалация).
   - Использование `manager_memory_*` (что и когда сохранять, когда искать).
   - Правила эскалации owner-у.
2. **A2. `roles/_common/lead-base.md`** — общая база для 11 лидов (safety-net + чек-листы + коммуникация).
3. **A3. 11 файлов `roles/<dept>/lead.md`** — специфика каждого лида (на основе knowledge-work-plugins). Можно итеративно: marketing-lead в Фазе 2, остальные в Фазе 3.
4. **A4. 49 файлов `roles/<dept>/<slug>.md`** для специалистов (5 ролей × 11 отделов ≈ 55, минус 6 dev которые уже есть ≈ 49 новых).
5. **A5. `templates/departments/<dept>-v2.yaml` × 11** — YAML-шаблоны с inherits_skills.
6. **A6. Обновить ADR-007** — переименовать «Advisor» в «Long-term memory layer», убрать `roles/advisor.md` / вкладку `/advisor` / `devboard-advisor.sh`. Оставить только техническую часть (SQL + MCP-tools). Status: Revised.

---

## References

- **`vendored/knowledge-work-plugins/`** (после реализации submodule) — источник 11 декомпозируемых плагинов от Anthropic.
- **README этого репо** — `https://github.com/anthropics/knowledge-work-plugins#how-plugins-work` — формат manifest + skills + .mcp.json.
- `roles/тимлид.md` — текущий файл, мигрируется в `roles/dev/lead.md`.
- `mcp_server/pride_tasks/tools.py` — точка регистрации новых MCP-tools.
- `dashboard/static/app.js` — UI Sidebar и чат.
- ADR-006 (`0006-token-optimization.md`) — prompt caching для управляющего критичен.

---

## Changelog

- **2026-05-25 — rev 1:** Initial draft. Источник:
  - Видение owner'а (планёрка, 3-уровневая иерархия, готовые шаблоны).
  - Анализ `https://github.com/anthropics/knowledge-work-plugins` (формат и декомпозиция).
  - Связи с ADR-003/004/005/007/008.
- **2026-05-25 — rev 2** (после обсуждения owner-а):
  - **§2.2 / §6.1**: планёрка opt-in, не default. Большинство задач — Управляющий распределяет напрямую.
  - **§2.4**: Phase 2 «Обсуждение» — лиды отделов **обсуждают между собой**, видят друг друга в shared planning-канале, 1-3 раунда обмена.
  - **§2.6.1 / §6.2**: **слияние Advisor с Управляющим**. Долгосрочная память переходит к Управляющему. ADR-007 переименован в «Long-term memory layer» (только техническая часть).
  - **§6.3**: убраны таймауты в минутах (re-entry policy вместо timeout).
  - **§6.5**: copy вместо submodule.
  - **§6.6**: dev-отдел остаётся как есть, без изменений моделей. Новые отделы — sonnet (специалисты + лиды), Управляющий — opus.
  - **§6.7**: 11 классических отделов (productivity/enterprise-search/bio-research/cowork-plugin-management — не берём).
  - **§6.8**: ADR-008 (channels) — после ADR-009, отложен.
  - Status: Draft → Proposed.

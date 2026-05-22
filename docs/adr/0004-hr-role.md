# ADR-004 — HR-роль и pipeline создания отдела

- **Status:** Proposed (2026-05-22)
- **Date:** 2026-05-22
- **Authors:** архитектор (devboard)
- **Epic:** v2.0 / HR — Масштабирование организационной структуры (label `v2.0/adr/hr`)
- **Supersedes:** —
- **Depends on:** ADR-003 (`docs/adr/0003-departments.md`) — модель `Department` и её хранилище.
- **Related:** ADR-002 (`docs/adr/0002-role-format.md`) — формат файлов ролей и валидатор E7.4; ADR-005 (`docs/adr/0005-inter-department.md`) — может вызывать HR при ненайденной роли в inter-department lookup.

## 1. Context

devboard в v1.x работает по схеме «одна организация = фиксированный набор семи ролей в `roles/`». Каждая новая роль — это ручная правка markdown-файла, согласование промта с owner'ом и redeploy. До v2.0 это работало: owner и архитектор писали роли сами, контролировали стиль, тестировали вживую.

С введением **отделов** (ADR-003) этого недостаточно. Owner хочет на лету создавать «отдел маркетинга», «отдел поддержки», «отдел продаж» — без того чтобы садиться писать пять markdown-файлов вручную. Параллельно три ограничения:

1. **Качество ролей.** Если LLM создаёт роль с нуля без шаблона — high variance: один прогон даёт хороший Marketing Lead, следующий даёт что-то странное. Owner не верит результату и теряет время на ревью каждого слова.
2. **LLM-drift.** LLM, генерирующий другие LLM-промты, склонен к патологиям: создавать destructive-роли («роль с правами удаления»), плодить дубликаты slug'ов, превышать разумные лимиты, выдумывать несуществующие модели в frontmatter. Без жёстких ограничений на стороне HR-сессии — багфикс будет постоянным.
3. **Auditable history.** Когда отдел создан, owner через полгода захочет понять «почему content-writer получил именно такой системный промт». Без явной привязки роли к шаблону + diff'у кастомизации это превращается в forensics.

Цель этой ADR — формализовать **HR-роль** (отдельная Claude-сессия с особым system-prompt) и **pipeline создания отдела** (диалог owner ↔ HR с явными состояниями), решающие все три проблемы.

Сейчас в кодовой базе нет ни HR-роли, ни папки `templates/departments/`, ни state machine для отделов. Связные модели `Department` и `Role` появляются в ADR-003 (`docs/adr/0003-departments.md`).

## 2. Decision

HR — отдельная Claude-сессия с system-prompt'ом `roles/hr.md` (формата ADR-002), которая принимает на вход желание owner'а («создай отдел маркетинга»), выбирает один из 5 MVP-шаблонов как базу, кастомизирует под owner'а через **диалоговый edit-loop**, и на выход регистрирует отдел в БД (ADR-003) + создаёт файлы ролей в `roles/<dept>/`.

Принимается **уровень автономии Hybrid (Level 2):** шаблон — это база, HR может менять состав ролей, имена, описания и системные промты (внутри жёстких constraints — см. §2.3).

### 2.1. YAML-схема шаблона департамента

Шаблоны живут в `templates/departments/<id>.yaml`. Это **версионируемый артефакт** в git, его пишут архитектор и техписатель руками — НЕ генерирует HR. HR только **читает** шаблон и **подставляет** в него кастомизации owner'а.

Каноничный пример:

```yaml
id: marketing-v1
name: Marketing
name_en: Marketing
description: |
  Generates content, manages brand voice, runs campaigns.
icon: 📣
roles:
  - slug: marketing-lead
    name_ru: Маркетинг-лид
    name_en: Marketing Lead
    model: claude-opus-4-7        # стратегия → opus
    skills: [strategy, planning, briefing]
    is_lead: true
    output_spec: |
      Plans campaigns, briefs writers, reviews drafts.
      Output: campaign brief (markdown), weekly plan (markdown), draft reviews (comments).
    system_prompt_template: |
      Ты — лид маркетинговой команды отдела "{{department.name}}".
      Ваш отдел: {{department.description}}.

      Состав твоей команды:
      {{#each department.roles}}
      - {{name_ru}} ({{slug}}): {{output_spec}}
      {{/each}}

      ...

  - slug: content-writer
    name_ru: Автор контента
    name_en: Content Writer
    model: claude-sonnet-4-6
    skills: [writing, editing, seo-light]
    is_lead: false
    output_spec: |
      Produces long-form articles, social posts, ad copy.
      Output: markdown drafts (1-3 per task), reviewed by marketing-lead.
    system_prompt_template: |
      Ты — автор контента в отделе "{{department.name}}".
      Твой лид — {{department.lead.name_ru}}.
      ...

  - slug: seo-researcher
    ...
  - slug: social-media-manager
    ...
```

#### Поля шаблона

##### Top-level (поля департамента)

| Поле | Тип | Обяз. | Constraints | Назначение |
|---|---|---|---|---|
| `id` | `str` | да | slug `^[a-z][a-z0-9-]*-v[0-9]+$` (`marketing-v1`, `support-v1`) | Версионированный идентификатор шаблона. Версия в id — чтобы не ломать ранее созданные отделы при обновлении шаблона. |
| `name` | `str` | да | 1…40 символов | Человекочитаемое имя (RU/основное) — попадает в БД (`departments.name`, ADR-003). |
| `name_en` | `str` | да | 1…40 ASCII | Английское имя для логов и open-source-документации. |
| `description` | `str` (multiline) | да | 1…500 символов | Что отдел делает в одном абзаце. Подставляется в `system_prompt_template` ролей. |
| `icon` | `str` | нет | 1 emoji или пусто | UI-иконка департамента. Default — пусто. |
| `roles` | `list[RoleTemplate]` | да | 1…8 элементов (см. §2.3 про лимит) | Состав ролей шаблона. |

##### Role-level

| Поле | Тип | Обяз. | Constraints | Назначение |
|---|---|---|---|---|
| `slug` | `str` | да | `^[a-z][a-z0-9-]{1,31}$`, уникален в `roles[]` шаблона | Идентификатор роли внутри отдела. Используется при генерации имени файла `roles/<dept>/<slug>.md` и в БД (ADR-003 — `roles.slug`). |
| `name_ru` | `str` | да | 1…40 символов | Имя роли для UI. |
| `name_en` | `str` | да | 1…40 ASCII | Английское имя. |
| `model` | `str` | да | непустая | Модель LLM (см. ADR-002 §2.2 — валидируется на стороне провайдера, мы не хардкодим список). |
| `skills` | `list[str]` | нет | 0…12 строк, slug-формат | Метки навыков для матчинга в inter-department lookup (см. ADR-005). Не влияют на LLM напрямую. |
| `is_lead` | `bool` | нет | default `false`; ровно один `true` среди `roles[]` шаблона | Маркер лида отдела. См. §2.3. |
| `output_spec` | `str` (multiline) | да | 50…800 символов | **Что роль производит**, не «о чём думает». Артефактно. Это ключевое поле против drift (см. §2.3). |
| `system_prompt_template` | `str` (multiline) | да | 200…30000 символов (≈30 KB ≈ 750 строк, см. ADR-002 §2.4 лимит 50 KB — оставляем запас на кастомизацию) | Шаблон системного промта с переменными в Mustache/Handlebars-стиле. |

#### Переменные шаблона

Поддерживаются переменные:

- `{{department.name}}`, `{{department.name_en}}`, `{{department.description}}`, `{{department.icon}}`
- `{{department.roles}}` — итерируемый список (только slug, name_ru, name_en, output_spec — без рекурсивных system_prompt'ов)
- `{{department.lead.slug}}`, `{{department.lead.name_ru}}`, `{{department.lead.name_en}}`
- `{{self.slug}}`, `{{self.name_ru}}`, `{{self.name_en}}`, `{{self.skills}}` — поля текущей роли
- `{{org.owner_name}}` — имя owner'а (для персонализации тона; берётся из БД)

Список **закрытый**. Незарегистрированная переменная (`{{user.email}}`) → `TemplateRenderError` при генерации. Это сознательно: расширение списка — новая ADR.

### 2.2. Pipeline state machine

Создание отдела — **диалог**, не one-shot. State machine (хранится в `hr_sessions` таблице, см. §6 Tasks):

```
state: idle
  │
  │  owner: POST /api/departments {name, description, hints}
  ▼
state: hr_planning
  │  HR-сессия спавнится с system-prompt = roles/hr.md
  │  HR читает 5 шаблонов из templates/departments/*.yaml
  │  HR выбирает ближайший шаблон по hints (см. §2.4 алгоритм матчинга)
  │  HR кастомизирует под description owner'а:
  │     — может добавить/удалить роли (внутри лимита 8)
  │     — может переименовать slug/name_ru/name_en
  │     — может переписать system_prompt_template
  │     — НЕ может изменить template_id, schema templates, output_spec формат
  │  HR постит план в inter-department channel (ADR-005) как структурированную
  │  карточку: "Plan v1: 4 роли — Marketing Lead, Content Writer, SEO Researcher,
  │  Social Media Manager. Кастомизация: усилен focus на B2B-tone..."
  ▼
state: awaiting_owner_review
  │  owner смотрит план в UI-модале:
  │    [Approve as is] → state: hr_activating
  │    [Edit] → отправляет текстовый комментарий в HR-сессию
  │    [Cancel] → state: cancelled
  │    timeout 72h без ответа owner'а → state: stale (требует manual resume)
  ▼ (если owner: Edit)
state: hr_revising  ◀───┐
  │  HR обновляет план │  loop max 5 итераций
  │  постит "Plan v2: ..."
  │  → awaiting_owner_review ──┘ (после 5-й итерации UI блокирует
  │                              "Edit", оставляя только "Approve as is"
  │                              или "Cancel & restart")
  ▼
state: awaiting_owner_approve
  │  owner: [Approve & Activate]
  ▼
state: hr_activating
  │  для каждой роли в плане:
  │    1. подставить переменные в system_prompt_template → готовый промт
  │    2. сформировать frontmatter (ADR-002 §2.2 обязательные поля)
  │    3. записать файл roles/<dept-slug>/<role-slug>.md
  │    4. вызвать E7.4 validator (frontmatter, размер, формат + усиления §2.3)
  │       └─ при invalid → HR переписывает только этот файл (max 3 попытки)
  │            └─ если все 3 невалидны → state: failed_activation
  │                 (роли остаются в /tmp, БД не тронута, owner видит ошибку)
  │  при успехе всех ролей:
  │    5. INSERT в departments (ADR-003) одной транзакцией с roles[]
  │    6. файлы из /tmp переезжают в roles/<dept-slug>/ (атомарно)
  ▼
state: active
  │  HR постит финальное "Отдел готов: 4 роли активированы" в inter-department channel
  │  owner получает Telegram-нотификацию (если включена)
  │  HR-сессия завершается (closeHandle)
```

#### Edge cases (явно описаны)

| Случай | Поведение |
|---|---|
| Owner закрывает модал на `awaiting_owner_review` без `Cancel` | state остаётся `awaiting_owner_review`. Через 72h cron-job переводит в `stale`. UI «My drafts» показывает stale-черновики, owner может resume. |
| Owner отказывается на `awaiting_owner_review` ([Cancel]) | state: `cancelled`. HR-сессия закрывается. Запись в `hr_sessions` сохраняется для audit. Никаких файлов и БД-записей не создаётся. |
| HR-валидатор отказывает 3 раза подряд на одной роли | state: `failed_activation`. БД не тронута, файлы не созданы. Owner видит «не удалось активировать роль `seo-researcher`: 3 попытки → invalid». Может: либо `restart` (новая сессия), либо открыть report и подать баг архитектору. |
| HR пытается превысить лимит 8 ролей в плане | На уровне HR system-prompt'а — запрещено (§2.3). Если LLM всё же выдаёт 9 — план-валидатор (server-side, до публикации в UI) отрезает план с ошибкой; HR пересоздаёт. Owner это не видит. |
| HR создаёт дубликат slug'а внутри плана | Аналогично: план-валидатор отбрасывает план, HR пересоздаёт. |
| HR создаёт отдел с slug, который уже существует в БД | План-валидатор проверяет уникальность `department.slug` (см. ADR-003). При коллизии — HR предлагает суффикс `-v2`. Если owner не одобряет — `cancelled`. |
| Itreration counter переполнен (>5) | UI блокирует кнопку `Edit`, оставляет `Approve as is` / `Cancel & restart`. Restart = новая `hr_session` с тем же initial input owner'а. |
| HR-сессия упала (network, OOM, claude CLI exited) | state: `crashed`. Записывается last-known план. Owner видит «HR-сессия упала, можно перезапустить» — кнопка `Resume` спавнит новую HR-сессию с тем же контекстом. |

### 2.3. Защита от LLM-drift

Защита — на трёх уровнях, потому что одного уровня LLM обходит.

**Уровень 1: HR system-prompt (`roles/hr.md`) — мягкие правила.**

HR-промт явно запрещает:

- Создавать роль с label `destructive` или с упоминанием «delete», «drop», «truncate» в `output_spec` (regex-blacklist в плане-валидаторе).
- Превышать лимит **8 ролей** в одном отделе (см. §2.5 обоснование лимита).
- Создавать дубликаты `slug` в `roles[]`.
- Создавать роль без `output_spec` или с `output_spec` короче 50 символов.
- Создавать больше одной роли с `is_lead: true` в плане.
- Менять `model`-список свободно — только из whitelist'а (`claude-opus-4-7`, `claude-sonnet-4-6`, `gpt-4o`, `gpt-4o-mini`, `llama3.1`, плюс что разрешает админ через env `HR_ALLOWED_MODELS`).
- Создавать роль с пустым или missing `system_prompt_template` (даже если кастомизация — взять из шаблона).

**Уровень 2: Server-side план-валидатор (до публикации owner'у).**

Перед тем как план уйдёт в `awaiting_owner_review`, backend прогоняет план через `validate_plan(plan, template) -> ValidationResult`:

- Все поля шаблона из §2.1 — типы, длины, regex'ы.
- Уникальность `slug` в `roles[]`.
- Ровно один `is_lead: true`.
- `len(roles)` ≤ 8.
- `template_id` указан и соответствует существующему шаблону.
- Никаких неизвестных полей.
- `system_prompt_template` рендерится с пустым контекстом без `TemplateRenderError` (валидируется грамматика, не семантика).

При invalid — HR получает обратную связь и пересоздаёт. Owner этого не видит.

**Уровень 3: E7.4 role-validator (расширение из ADR-002) — при активации.**

Активация (`hr_activating`) генерирует файл `roles/<dept>/<slug>.md` и прогоняет его через стандартный `load_role()` (ADR-002 §2.5). К существующей валидации добавляются три проверки:

- `output_spec` присутствует в `extras` или как top-level (зависит от итогового решения интеграции с ADR-002 — см. §4 Open questions); длина 50…800 символов.
- В отделе ровно одна роль с `is_lead: true` — кросс-файл-проверка (E7.4 принимает список ролей одного департамента).
- `system_prompt` (тело markdown после frontmatter) ≤ **500 строк** (≈12 KB) — мягче чем 50 KB ADR-002, но строго для HR-сгенерированных ролей: ручные роли (тимлид) могут быть длиннее, HR-роли — нет, потому что HR любит «подстраховаться» и плодит секции.

**Auditable history.**

Каждая HR-сгенерированная роль обязана иметь в `extras` frontmatter'а (ADR-002 §2.3):

```yaml
extras:
  hr_meta:
    template_id: marketing-v1
    department_id: dept_abc123
    hr_session_id: hr_xyz789
    created_by: hr
    created_at: 2026-05-22T14:32:11Z
    customizations:
      - "renamed: content-writer → copywriter"
      - "added skill: brand-voice-b2b"
```

Owner всегда видит финальный пакет ролей перед активацией (state `awaiting_owner_approve`) — в UI это финальная подтверждающая карточка с diff'ом «base template ↔ финальный план», чтобы кастомизация была эксплицитной.

### 2.4. Edit-loop UI (frontend specification)

Modal `"New Department"` — компонент в дашборде. Состоит из:

- **Header:** название модала, name owner'а («Hi пользователь — let's build a department»), кнопка close.
- **Initial form (state `idle`):**
  - Text input «Department name» (free-form, RU/EN).
  - Textarea «What it does» (1…500 символов) — попадает в `description`.
  - Textarea «Hints» (optional) — «hint: B2B SaaS», «hint: focus on TikTok» (HR использует для матчинга и кастомизации).
  - Button `[Start]` → POST `/api/departments` → state переходит в `hr_planning`.
- **Chat-pane (states `hr_planning` … `awaiting_owner_approve`):**
  - Embedded chat-history между HR и owner (read-only сверху, input снизу).
  - Каждый план HR — структурированная карточка:
    - Шаблон-источник: `marketing-v1`
    - Список ролей: иконки, имена, output_spec preview
    - Diff vs base template (highlight: added/removed/renamed)
    - Кнопки `[Approve as is]` / `[Edit]` / `[Cancel]`
  - Edit-pane: появляется при клике `[Edit]`. Textarea «Что изменить?» + кнопка `[Send to HR]`. Сообщение уходит в HR-сессию как user-message.
  - **Iteration counter** в углу: «Iteration 2/5». На 5-й — counter становится красным, `[Edit]` disabled, остаются `[Approve as is]` / `[Cancel & restart]`.
- **Final card (state `awaiting_owner_approve`):**
  - Полный пакет ролей с раскрытыми system_prompts (collapsible).
  - Большая кнопка `[Approve & Activate]`.
  - Маленькая `[Cancel]` (возврат к chat'у).
- **Activation (state `hr_activating`):** прогресс-бар «Validating role 1/4… Activating role 2/4…». 5-30 секунд.
- **Success (state `active`):** конфетти-overlay, ссылка на новый отдел, кнопка `[Open department]`.

Чат отдельно НЕ открывается — это **iframe внутри модала**, чтобы owner не отвлекался на параллельные задачи. State хранится server-side (`hr_sessions`), модал — stateless: при перезагрузке восстанавливает state из сервера.

### 2.5. Обоснование лимита 8 ролей

Лимит **`max 8 ролей`** на отдел (не считая опциональных, добавляемых вручную после активации) — не произвольный.

- Lead отдела должен помнить контекст всех подчинённых (имена, специализации, текущие задачи) при делегировании. При 9+ ролях контекст начинает деградировать на Claude Sonnet 4.6 (≈80K useful window): уходит в `<thinking>` блок, ответы делегирования становятся random.
- 5 MVP-шаблонов укладываются в 3-4 роли каждый — лимит 8 даёт двукратный запас на кастомизацию owner'а.
- Inter-department channel (ADR-005) при матчинге по skills тоже деградирует при больших отделах — больше шанс на ambiguous matches.

Если когда-нибудь понадобится 12-15 ролей в одном отделе — это сигнал что отдел нужно **разделить** (Marketing → Content + Performance), а не растить. YAGNI: повышаем лимит новой ADR-004-rev, если case появится.

## 3. Consequences

**Плюсы**

- **Масштабируемое создание отделов.** Owner создаёт «отдел поддержки» за 5 минут диалога, не открывая ни одного `.md` файла. Барьер на следующие отделы — минимальный.
- **Качество гарантируется шаблоном.** Шаблоны написаны архитектором/техписателем вручную, проверены вживую. HR не создаёт промты с нуля — только **подставляет переменные и опционально правит**, что радикально снижает variance.
- **Auditable history.** `extras.hr_meta` в frontmatter каждой роли + запись в `hr_sessions` — через год owner может ответить на вопрос «почему так» без forensics.
- **Защита от LLM-drift на трёх уровнях.** Один уровень LLM иногда обходит, три — практически нет.
- **Edit-loop даёт контроль без боли.** Owner правит план словами, HR воплощает — не нужно знать markdown/YAML.
- **Open-source readiness.** 5 шаблонов в `templates/departments/` — это документация-как-код. Контрибьютор копирует один из них, добавляет свой `engineering-v1.yaml`, открывает PR.

**Минусы / риски**

- **HR-сессии — это $$.** Каждое создание отдела — диалог 5-10 turns на Opus, по нашим прикидкам $0.50…$2.00 за отдел. Это OK для owner-driven action, но если кто-то начнёт спамить — нужен rate-limit (см. §6 Tasks).
- **LLM может зацикливаться.** На 4-й итерации edit-loop HR может «терять контекст» и возвращать предыдущую версию плана. Mitigation: itreration counter жёсткий (5), после — restart. Long-term mitigation — мониторить через `hr_meta` и оптимизировать HR-промт.
- **Edit-loop может frustrate owner'а.** «Я три раза попросил убрать SEO, он добавляет снова». Mitigation: на 3-й итерации UI показывает warning «HR не понимает правки — рекомендуем restart с явными hints». Это софтверный мост, не решение.
- **Шаблоны устаревают.** `marketing-v1` через год может быть outdated. Версионирование (`-v1` в id) даёт нам путь: создаём `marketing-v2`, старые отделы НЕ мигрируют (locked на `-v1` через `template_id`), новые создаются на `-v2`. Это сознательная цена за стабильность.
- **Шаблон как сильный bias.** HR редко отклоняется далеко от шаблона (это и плюс, и минус). Owner, который хочет «отдел маркетинга, но всё нестандартно», застрянет — для него остаётся ручной путь (написать роль `.md` самому, не через HR). Документируем явно в README.
- **`output_spec` обязателен — это новое поле для ADR-002.** Нужно расширение role-format (либо как top-level поле, либо как структурированный `extras.output_spec`). См. §4 Open questions.
- **Зависимость от ADR-003.** Если ADR-003 решит хранить `Department` не в БД, а в файлах — нужна ревизия §2.2 (state machine хранит state в БД). Mitigation: жёсткий depends_on, ADR-004 не вступает в `Accepted` пока ADR-003 не accepted.

## 4. Alternatives Considered

### 4.1. Level 1 (template-only, без LLM)

«HR — это не LLM, а простой template-renderer. Owner выбирает шаблон через dropdown, шаблон рендерится 1:1, отдел создан.»

**Отвергнуто.** Нет персонализации под language/industry/style owner'а. «Marketing» для бутика косметики ≠ «Marketing» для B2B SaaS, но шаблон один на всех — придётся либо плодить шаблоны (`marketing-cosmetics-v1`, `marketing-b2b-saas-v1`, …), либо мириться с generic-промтами. Owner будет править файлы руками после создания — а это именно то от чего уходим.

### 4.2. Level 3 (free-form, LLM создаёт с нуля)

«HR — это полностью свободная Claude-сессия, без шаблонов. Owner говорит "хочу маркетинг", HR придумывает роли сам.»

**Отвергнуто.** Высокий риск LLM-drift (см. §2.3 — три уровня защиты были бы недостаточны без шаблона как baseline). Variance между прогонами слишком высокая — owner не сможет доверять результату. Нет baseline качества, на который можно опереться при тестах.

Кроме того, Level 3 убивает auditable history: нет `template_id`, не от чего считать «кастомизацию». Через год не понятно, что HR придумал, а что owner попросил.

### 4.3. One-shot HR (без edit-loop)

«HR за один запрос выдаёт финальный пакет ролей, owner либо approves либо restarts.»

**Отвергнуто.** Owner не верит без diff'а — будет каждый раз restart-ить пока не получит что-то на 80% похожее на ожидание. Edit-loop даёт **контроль постепенный**: «убери эту роль», «переименуй ту», «усиль focus на X» — без полной пересоздачи каждый раз.

Кроме того, на one-shot HR может выдавать что-то близкое к запросу но не идеальное, и owner либо мирится (плохое качество), либо restart (потеря 30 секунд + $0.30). Edit-loop делает обе ситуации лучше.

### 4.4. Limit > 8 ролей или unlimited

«Зачем лимит, пусть owner сам решает.»

**Отвергнуто.** Контекст-окно LLM начинает деградировать (см. §2.5). Coordination Lead'ом становится трудной (когда у лида 12 подчинённых, делегирование становится случайным). Лучше **разделить отдел** на два — это нормальная организационная практика и в живых компаниях. YAGNI: лимит снимаем когда появится конкретный case, не раньше.

### 4.5. HR — это extension существующей роли (например `architect.md`)

«Зачем отдельная HR-роль — пусть архитектор создаёт отделы как часть своих обязанностей.»

**Отвергнуто.** Архитектор — это reviewer, пишущий ADR. У него другой system-prompt, другой набор инструментов, другая дисциплина (YAGNI, composition > inheritance). HR — это **мета-агент**, который создаёт ролей: специализированный prompt-engineer + орг-дизайнер. Смешивать — значит делать `roles/architect.md` гигантским и расфокусированным.

Plus HR имеет специфический tool-allowlist: ему нужны `read_template`, `validate_role`, `create_department_in_db`, которые архитектору не нужны. Разделение чище.

### 4.6. Шаблоны как Python-код, не YAML

«Шаблоны на Jinja2 + Python helper-функции дают больше гибкости.»

**Отвергнуто.** Шаблоны должны быть **читаемы non-coder'ом** — техписатель и архитектор пишут их, не бэкенд. YAML + Mustache-переменные читается как документ. Python-код требует runtime — а нам нужна валидация шаблона на CI без выполнения. Кроме того, YAML-шаблон легче ревьюить в PR (diff читается).

## 5. Migration plan

devboard v1.x не имеет HR-роли и отделов. Миграция — **forward-only** (создание новых артефактов), без правки существующих:

1. **Архитектор + техписатель:** написать 5 YAML-шаблонов в `templates/departments/`:
   - `marketing-v1.yaml`: Marketing Lead + Content Writer + SEO Researcher + Social Media Manager (4 роли).
   - `design-v1.yaml`: Design Lead + UI Designer + Visual Designer + UX Researcher (4 роли).
   - `sales-v1.yaml`: Sales Lead + SDR + Account Manager (3 роли).
   - `support-v1.yaml`: Support Lead + Tier 1 Agent + Tier 2 Specialist + Knowledge Writer (4 роли).
   - `operations-v1.yaml`: Ops Lead + Process Analyst + Automation Engineer (3 роли).
2. **Архитектор:** написать `roles/hr.md` (формат ADR-002) — system-prompt HR-роли с явными запретами (§2.3 уровень 1).
3. **Бэкенд:** реализовать HR pipeline state machine (см. §6 Tasks).
4. **Бэкенд:** расширить E7.4 валидатор (output_spec, is_lead unique, prompt size).
5. **Бэкенд:** расширить ADR-002 RoleConfig для поля `output_spec` (либо как top-level, либо в `extras.hr_meta` — резолвится в Open questions §7.1).
6. **Frontend:** реализовать модал «New Department».
7. **QA:** smoke + edge cases.
8. **Техписатель:** README раздел «Creating new departments».

Активация HR — feature flag `HR_ENABLED=true` в env. До этапа QA — фича доступна только в dev, в проде disabled. После flag flip — доступна всем owner'ам.

## 6. Tasks

### Backend (`v2.0/hr/backend`)

1. **HR pipeline state machine.** Таблица `hr_sessions(id PK, department_id_pending, owner_id FK, state TEXT, template_id, plan_json, iterations INT, created_at, updated_at, last_message_at)`. Колонка `state` принимает значения из §2.2. Триггер `updated_at = now()` на любом UPDATE. Cron-job переводит `awaiting_owner_review` в `stale` при `last_message_at < now() - 72h`.
2. **REST endpoints** (под `/api/departments/`):
   - `POST /api/departments` — создать draft, спавнить HR-сессию, начать `hr_planning`. Возвращает `{session_id, initial_plan, state}`.
   - `POST /api/departments/<id>/hr/plan` — (internal) HR публикует план, переводит в `awaiting_owner_review`.
   - `POST /api/departments/<id>/hr/revise` — owner шлёт comment в HR; backend проксирует в HR-сессию, переводит state в `hr_revising` → потом в `awaiting_owner_review` с обновлённым планом.
   - `POST /api/departments/<id>/hr/approve` — owner approves, переводит в `hr_activating`, запускает activation pipeline.
   - `POST /api/departments/<id>/hr/cancel` — owner cancels, переводит в `cancelled`.
   - `GET /api/departments/<id>/hr` — текущий state, план, история сообщений.
3. **Template loader + validator.** Модуль `mcp_server/templates/department_loader.py` (или аналог в `dashboard/hr.py`): `load_template(template_id) -> DepartmentTemplate` (pydantic-модель по §2.1), `validate_plan(plan, template) -> ValidationResult` (§2.3 уровень 2).
4. **Plan-to-roles generator.** Функция `materialize_plan(plan, department) -> list[RoleFile]`: подстановка переменных (см. §2.1 список), сборка frontmatter (ADR-002), запись в `/tmp` сначала, атомарный rename в `roles/<dept>/` при success всех файлов.
5. **E7.4 валидатор — усиление.** Доделать `roles/validator.py` (из ADR-002 E7.4): добавить проверки `output_spec` (длина 50…800), `is_lead` unique-per-department (принимает список ролей), system_prompt size ≤ 500 строк когда `hr_meta.created_by == "hr"`.
6. **Rate-limit.** `HR_MAX_DEPARTMENTS_PER_HOUR=3` per owner (env, default 3). 429 при превышении.
7. **Auditable history.** Все `hr_sessions` храним forever (не удаляем на success). При создании отдела attach `hr_session_id` → `department.hr_session_id` (см. ADR-003).
8. **HR system-prompt enforcement.** В `roles/hr.md` явно прописать запреты §2.3 уровень 1 (мягкие правила). Регрессионные тесты на HR-промт — задача QA.

Итого: **8 задач**.

### Frontend (`v2.0/hr/frontend`)

1. **Modal `New Department`** — основной компонент, мультистейтовый (см. §2.4).
2. **Initial form** — name + description + hints input + `[Start]` button.
3. **Chat-pane с iframe** — embedded chat-history HR ↔ owner, structured cards для планов.
4. **Plan card component** — рендерит план: шаблон-источник, список ролей с output_spec preview, diff vs base template, кнопки Approve/Edit/Cancel.
5. **Edit-textarea + send** — компонент для отправки comment'ов в HR-сессию.
6. **Iteration counter UI** — показывает «Iteration N/5», красный на 5-й, disable `[Edit]` после.
7. **Final approve card** — раскрываемый полный пакет ролей с system_prompts, большая кнопка `[Approve & Activate]`.
8. **Activation progress bar** — «Validating role 1/4…», polling state каждые 1с.
9. **Success view** — конфетти, ссылка на новый отдел.
10. **Stale draft recovery** — UI «My drafts» с кнопкой `[Resume]` для stale-сессий.

Итого: **10 задач**.

### QA (`v2.0/hr/qa`)

1. **Smoke create-department (happy path).** Создать `marketing-v1` через UI без правок, проверить: файлы в `roles/marketing/`, запись в БД (ADR-003), `hr_session.state = active`.
2. **Smoke + custom edits.** Создать отдел с 2-3 правками в edit-loop, проверить diff в `hr_meta.customizations`.
3. **Edge: HR не может валидировать роль 3 раза.** Mock-валидатор всегда invalid → state: `failed_activation`, БД не тронута, файлы не созданы.
4. **Edge: owner отказывается на awaiting_review.** [Cancel] → state: `cancelled`, нет файлов, нет БД-записи, `hr_session` сохранена.
5. **Edge: HR создаёт дубликат slug в плане.** План-валидатор отбрасывает, HR пересоздаёт. Проверить через mock HR-ответ.
6. **Edge: HR пытается > 8 ролей.** Аналогично — план-валидатор отбрасывает.
7. **Edge: HR пытается создать destructive-роль.** План-валидатор отбрасывает (regex `output_spec`).
8. **Edge: HR пытается non-whitelist model.** План-валидатор отбрасывает.
9. **Edge: iteration counter переполнен.** На 6-й [Edit] клике UI блокирует, доступны только Approve / Cancel & restart.
10. **Edge: stale draft.** Создать draft, подождать > 72h (или mock-time), проверить переход в `stale`, восстановление через `[Resume]`.
11. **Edge: HR-сессия упала.** Killing процесса HR в середине → state: `crashed`, `[Resume]` спавнит новую.
12. **Edge: rate-limit.** Создать 3 отдела за час, 4-й → 429.
13. **Regression: HR system-prompt.** Тест на 5 «отравленных» запросов от owner'а («сделай роль с правами удаления», «дай мне 20 ролей», …) — HR отказывает корректно.

Итого: **13 задач**.

### Техписатель (`v2.0/hr/docs`)

1. **README раздел «Creating new departments»** — walkthrough HR flow (скриншоты модала, объяснение state machine для owner'а — без технических деталей).
2. **`docs/templates/README.md`** — гайд «How to write a new department template» для контрибьюторов: схема YAML, переменные, как тестировать локально.
3. **`docs/hr-troubleshooting.md`** — типовые проблемы: «HR не понимает мои правки» (restart с явными hints), «отдел не активируется» (читать ошибку валидатора), «как удалить отдел» (ссылка на ADR-003 / UI).
4. **Inline-документация в `templates/departments/marketing-v1.yaml`** — комментарии в YAML, что значит каждое поле, ссылка на ADR-004.

Итого: **4 задачи**.

### Архитектор (parallel)

Не задача этой ADR, но **архитектор владеет** шаблонами в `templates/departments/` (5 файлов). Эта работа — параллельно с реализацией бэкенда:

1. Написать `marketing-v1.yaml`, `design-v1.yaml`, `sales-v1.yaml`, `support-v1.yaml`, `operations-v1.yaml`.
2. Написать `roles/hr.md` (system-prompt HR).

## 7. Open questions

### 7.1. `output_spec` — top-level поле RoleConfig или `extras.hr_meta`?

ADR-002 §2.2 фиксирует 5 обязательных полей: `schema_version`, `name`, `description`, `llm`, `model`. Добавлять `output_spec` как 6-е обязательное — breaking change ADR-002 (потребуется ADR-002-rev и миграция 7 существующих ролей).

**Предложение:** `output_spec` живёт в `extras.hr_meta.output_spec` для HR-сгенерированных ролей; обязательное **только для них** (валидируется E7.4 при `hr_meta.created_by == "hr"`). Ручные роли (тимлид, архитектор) опционально могут добавить — но не обязаны.

**Финальное решение** — за тимлидом + архитектором ADR-002 (одно слово в issue, не отдельная ревизия).

### 7.2. HR-роль использует Opus или Sonnet?

HR — мета-агент, который **создаёт промты для других моделей**. Опыт показывает: prompt engineering лучше делает Opus (нюансы, structure). Но HR-сессии — на 10 turn'ов диалог, это $$.

**Предложение:** HR на Opus 4.7 (см. ADR-001 §6.2 для default-провайдера). Альтернатива — Sonnet 4.6 с фолбэком на Opus при отказе валидатора > 2 раз. Финальное решение после первых 10 реальных HR-сессий и сбора cost-данных.

### 7.3. Конкуренция за `department.slug`?

Если два owner'а одновременно создают отдел с одинаковым slug (`marketing`) — план-валидатор увидит коллизию только при втором approve. Решение: SELECT FOR UPDATE на `departments.slug` при approve, либо unique constraint + retry-loop.

**Предложение:** unique constraint в БД (см. ADR-003 §миграции) + при IntegrityError на activation — HR пересоздаёт slug с суффиксом `-1`, `-2`. Owner видит warning.

### 7.4. Удаление отдела — кто и как?

Эта ADR создаёт отделы. Удаление — выходит за scope. Если owner хочет удалить отдел созданный HR — это **отдельный flow** (depends on ADR-003 §удаление, если он покрывает; иначе — новая ADR-006-delete-department).

## 8. References

- ADR-002 — `docs/adr/0002-role-format.md` (формат файлов ролей, валидатор E7.4)
- ADR-003 (planned) — `docs/adr/0003-departments.md` (модель Department, хранилище)
- ADR-005 (planned) — `docs/adr/0005-inter-department.md` (inter-department channel, skill matching)
- Anthropic Claude skills format — `https://docs.claude.com/en/docs/claude-code/skills`
- Mustache / Handlebars syntax — `https://mustache.github.io/mustache.5.html`
- Prompt engineering for prompt-generation (meta-prompting) — Anthropic best practices

## Changelog

- **2026-05-22:** Initial draft (Proposed) — задача `1c8bb253772c` (v2.0/adr/hr).

# ADR-005 — Inter-department правила (Lead→Lead, no decline, capacity view)

- **Status:** Proposed (2026-05-22)
- **Date:** 2026-05-22
- **Authors:** архитектор (devboard)
- **Epic:** v2.0 / Multi-department coordination (parent task `d673a1d6c156`)
- **Supersedes:** —
- **Depends on:**
  - **ADR-003** (`docs/adr/0003-departments.md`) — модель `departments` и колонка `tasks.department_id`.
  - **ADR-004** (`docs/adr/0004-hr-role.md`) — HR-роль и pipeline создания новых ролей в существующем отделе.
- **Related:** ADR-002 (`docs/adr/0002-role-format.md`) — `name` и `tools` ролей; Lead роли имеют отдельный allowlist для cross-task API.

## 1. Context

В v1.x devboard был **моно-командой**: один тимлид, ~7 ролей, одна очередь задач. В этой топологии любая роль могла обратиться к любой другой через тимлида — формальный протокол был не нужен, потому что «отдел» был один.

В v2.0 (см. ADR-003) появляются **несколько отделов**, у каждого свой Lead, свой набор ролей и своя очередь задач. Это сразу же ломает прежнюю модель коммуникаций. Конкретный кейс хаоса без правил:

> `marketing-copywriter` доходит до пункта «нужен баннер». Он напрямую дёргает `design-illustrator` (роль другого отдела) через `create_task` → задача появляется в очереди дизайна без ведома `design-lead`. Параллельно `support-engineer` (тоже без согласования) кидает в дизайн «срочно перерисуй иконку». `design-lead` обнаруживает в своей очереди 12 задач от 5 разных rank-and-file ролей чужих отделов, без приоритезации, без audit trail, без понимания кто за что отвечает. Owner (пользователь) не видит ничего — задачи не проходят через его Inbox.

Без формального cross-department протокола неизбежны:

1. **Бесконтрольная нагрузка на чужой отдел** — любая роль может «нанять» соседей; очередь target-отдела заполняется шумом, Lead теряет контроль над своим pipeline.
2. **Отсутствие audit trail** — кто кого о чём попросил восстанавливается только по чату/комментариям; для P1-задач это критично.
3. **Decline-chain'ы** — target Lead, не имея формального обязательства, начинает отклонять «не свои» задачи; sender Lead идёт жаловаться owner'у; работа стоит. Это особенно вредно когда отделы под управлением LLM: модель плохо «торгуется» в свободном чате.
4. **ETA-фантазии** — если cross-task пытается дать `deadline`, обещание делает LLM, который не знает реального времени выполнения. Пользователь видит «design к четвергу», верит, отдел не успевает — доверие к системе ломается.
5. **Skill-mismatch без выхода** — sender просит «нарисовать мобайл-баннер», у дизайн-отдела нет роли с этим скиллом. Что дальше? Без правила — задача висит, никто не отвечает.

Эта ADR формализует **протокол кросс-департаментной работы**: кто кому может создавать задачи, как они эскалируются, как визуализируется загрузка, что делать когда нужной роли нет.

Решения ниже **уже приняты owner'ом**; ADR их специфицирует, не переоценивает.

## 2. Decision

### 2.1. Модель кросс-задачи (расширение таблицы `tasks` из ADR-003)

В таблицу `tasks` (см. ADR-003 §2.x) добавляются две колонки:

```sql
ALTER TABLE tasks ADD COLUMN requester_department_id TEXT
    REFERENCES departments(id);
ALTER TABLE tasks ADD COLUMN requester_role_slug TEXT;
-- existing tasks.department_id остаётся = target department
```

Семантика:

- `department_id` — **target** отдел (куда задача попала в очередь). Это уже существующее поле из ADR-003, не меняем.
- `requester_department_id` — отдел-заказчик. `NULL` для intra-department задач (классический случай: roles одного отдела работают друг с другом через своего Lead).
- `requester_role_slug` — `name` роли заказчика (см. ADR-002 §2.2). Обязательно = Lead заказчика (`*-lead`) или `owner`. Проверка на стороне backend (см. §2.2).

**Определение inter-department task:**

```
inter_department := (requester_department_id IS NOT NULL)
                AND (requester_department_id != department_id)
```

Если оба department_id совпадают — это intra-department, обычная задача. Если `requester_department_id IS NULL` — legacy v1.x задача (см. §7 Migration).

Индекс:

```sql
CREATE INDEX idx_tasks_inter_dept
    ON tasks(department_id, requester_department_id, status)
    WHERE requester_department_id IS NOT NULL
      AND requester_department_id != department_id;
```

Используется UI для capacity badges (§2.4) и Inbox-секциями (§2.3, §2.5).

### 2.2. Workflow создания inter-task

REST endpoint (детали реализации — задача бэкенду, не ADR):

```
POST /api/departments/<target_id>/tasks
Body (JSON):
{
  "title": "draw onboarding banner",
  "description": "...",
  "priority": "P3",                       # P1 | P2 | P3
  "labels": ["banner", "marketing"],
  "requester_department_id": "marketing",
  "requester_role_slug": "marketing-lead"
}
```

Pipeline на backend:

```
1) AuthZ
   - caller (по сессии/API-key) — это subagent с role.name == requester_role_slug
   - role.name должно совпадать с одним из:
       (a) <requester_department>-lead   (Lead отдела-заказчика)
       (b) owner
   - иначе → 403 Forbidden
       {"error": "only Lead or owner can create cross-department tasks",
        "your_role": <name>}

2) Target dept существует и не архивирован
   - SELECT status FROM departments WHERE id = <target_id>
   - if not found → 404
   - if status = 'archived' → 410 Gone
       {"error": "target department archived", "department_id": <target_id>}

3) Skill-match (best-effort)
   - target_dept.roles → собираем union of role.skills (см. ADR-003)
   - if labels ∩ required_skills пусто И description-keywords не пересекаются:
       → 409 Conflict
       {"error": "no matching role in target department",
        "offer_create_role_via_hr": true,
        "suggested_role_spec": {
            "skills": [...derived from labels/description...],
            "model_hint": "<haiku|sonnet|opus>"
        }}
     → клиент (sender Lead) показывает owner'у диалог «создать роль X через HR?» (см. §2.8)

4) Rate-limit
   - см. §6.1: 10 P3 / 24h / (requester_department → target_department)
   - if exceeded → 429 Too Many Requests
       {"error": "rate limit", "reset_at": <ts>}

5) Escalation gate
   - if priority in ('P1', 'P2'):
        status = 'needs_approval'
        requires_approval = true
        → запись попадает в Inbox owner'а (§2.5)
   - if 'requires_budget' in labels OR 'destructive' in labels:
        status = 'needs_approval'
        requires_approval = true
   - else (P3, без destructive/budget):
        status = 'todo'
        → запись попадает в Inbox target Lead'а (§2.3)

6) Insert + audit
   - INSERT INTO tasks (..., requester_department_id, requester_role_slug, ...)
   - event log → inter-department channel (§2.6):
        [marketing → design] #<id> "<title>" (<priority>) — created
```

Никакой Lead не может **создать задачу мимо своего отдела** иначе как через этот endpoint. Прямой `mcp__devboard-tasks__create_task(department_id=<чужой>)` — закрыт на уровне MCP-сервера (см. Tasks для бэкенда §8).

### 2.3. UI: Inbox target Lead'а

В дашборде target Lead'а (`/dashboard/<dept_id>`) появляется новая секция:

```
Sidebar Inbox:
├─ Approvals (existing)
├─ Inter-department requests   ←  NEW
└─ Reviews (existing)
```

Карточка в секции:

```
┌─ inter-dept (origin: marketing) ─────────────────────────┐
│  Marketing → Design                                       │
│  "draw onboarding banner X"                               │
│  P3 · labels: banner, marketing · requested by: marketing-lead │
│                                                           │
│  [ Take into queue ]   [ Counter-propose ]                │
└───────────────────────────────────────────────────────────┘
```

Визуальные требования:

- Лейбл `inter-dept` фиксированного оранжевого цвета (отличается от intra).
- Origin-отдел — цветная плашка слева (цвет берётся из `departments.color`, ADR-003).
- Кнопка «Take into queue» — `PATCH /api/tasks/<id>` `status: todo → in_queue` (или сразу `in_progress` если pool свободен).
- Кнопка «Counter-propose» открывает modal с предложением:
  - изменить priority (например P3 → P3-low),
  - изменить scope (свободный текст комментария),
  - кнопка «Send counter» — статус остаётся `todo`, в audit-log пишется `counter-proposed`, sender Lead получает push в свой Inbox.

**Принципиально: кнопки «Decline» НЕТ.** Counter-proposal — единственная альтернатива немедленному взятию в очередь. Это сознательное ограничение, обоснование — §4.4.

### 2.4. Capacity view (frontend)

#### Sidebar badges

На каждой плашке отдела в общем sidebar (виден всем Lead'ам и owner'у):

```
┌─────────────────────────────────────┐
│  ● Design          (3 в работе, 12 в очереди) │
│  ● Marketing       (1 в работе, 4 в очереди)  │
│  ● Engineering     (5 в работе, 2 в очереди)  │
└─────────────────────────────────────┘
```

Числа берутся из:

```sql
SELECT
  COUNT(*) FILTER (WHERE status = 'in_progress')  AS in_work,
  COUNT(*) FILTER (WHERE status IN ('todo','in_queue')) AS in_queue
FROM tasks
WHERE department_id = <dept>
  AND archived_at IS NULL
GROUP BY department_id;
```

При hover на цифру очереди — выпадает компактный список задач в очереди этого отдела с их `position` (рассчитывается как `ROW_NUMBER() OVER (PARTITION BY department_id ORDER BY priority, created_at)`).

#### Position preview при создании cross-task

Когда sender Lead заполняет modal «Создать задачу для отдела X», в momentum-моменте перед submit показывается preview:

```
┌─ Создание задачи для Design ──────────┐
│  Priority: P3                          │
│  Title: draw onboarding banner         │
│                                        │
│  ↓                                     │
│                                        │
│  Будет 5-й в очереди (из 12)           │
│  [ Создать ]   [ Отмена ]              │
└────────────────────────────────────────┘
```

Position рассчитывается серверным endpoint `GET /api/departments/<id>/queue-position-preview?priority=P3` — возвращает `position: int, total: int`, без боковых эффектов.

#### Никаких ETA / deadlines

**Принципиальное решение:** ни в одном UI inter-department системы НЕ показывать:

- estimated completion time / ETA,
- deadlines, кроме тех, что задал owner вручную,
- «займёт ~2 часа» / «обычно делается за день» и т.п.

Обоснование:

1. **LLM не знает сколько займёт.** Время выполнения задачи в LLM-управляемом отделе зависит от: длины context'а, частоты cache-hit, доступности MCP-tools, retry-логики, ситуативной сложности (которая видна только при попытке решить). Ни одна из этих величин не предсказуема статистически на наших объёмах.
2. **Фейковые ETA снижают доверие.** Если система показала «к четвергу», а сделали к следующему понедельнику — пользователь перестаёт верить вообще всем числам в UI. Лучше не показывать ничего, чем показать неверное.
3. **Position-based — честный сигнал.** «Ты 5-й из 12 в очереди» — это **факт текущего состояния**, не прогноз. Sender Lead сам может оценить нагрузку отдела (по динамике числа в очереди день-к-дню) и решить, нужно ли эскалировать owner'у для приоритезации.

Если когда-нибудь окажется, что отдельные отделы (например `engineering` с детерминированными задачами вроде «прогнать pytest») имеют предсказуемые тайминги — это будет отдельная ADR-005-rev, опт-ин per dept. По умолчанию — position-only.

### 2.5. Эскалация owner'у

Когда задача создаётся с `status = 'needs_approval'` (см. §2.2 step 5) — она появляется в Inbox owner'а:

```
Owner's Inbox:
├─ Direct messages (existing)
├─ Department requests          ←  NEW
└─ HR pipeline (existing from ADR-004)
```

Карточка в «Department requests»:

```
┌─ needs approval (cross-dept, P1) ────────────────────────┐
│  Marketing → Design                                       │
│  "rebrand all banners for Q3 launch"                      │
│  P1 · labels: requires_budget                             │
│  requested by: marketing-lead                             │
│  ↓                                                        │
│  Будет 1-й в очереди Design (из 12)                       │
│                                                           │
│  [ Approve ]   [ Reject ]   [ Modify ]                    │
└───────────────────────────────────────────────────────────┘
```

Действия owner'а:

- **Approve** → `status: needs_approval → todo`, задача попадает в Inbox target Lead'а как обычная inter-dept request (§2.3); audit `approved-by-owner`.
- **Reject** → `status: needs_approval → cancelled`, sender Lead получает push с причиной (free-text от owner'а); audit `rejected-by-owner` + reason.
- **Modify** → owner может изменить priority и/или labels, затем approve. Audit пишет diff (что изменилось).

Эти три действия — единственные, доступные owner'у на `needs_approval` cross-task. Никаких «вернуть на доработку» / «отложить» — это специально для борьбы с indecision-петлями.

### 2.6. Audit trail в inter-department channel

Существует **один глобальный канал** (логическая сущность, в реализации — отдельная таблица `inter_department_events` или дашборд-секция, на усмотрение бэкенда), куда пишутся все события cross-task'ов:

```
[marketing → design] #abc123 "draw banner X" (P3) — created
[marketing → design] #abc123                       — taken into queue, position 5/12
[engineering → support] #def456 "investigate bug Y" (P1) — created (needs_approval)
[owner → engineering→support]   #def456            — approved-by-owner
[engineering → support] #def456                    — counter-proposed: priority P1→P2 (capacity)
[marketing → design] #abc123                       — completed
[hr → design]      #ghi789 "create role mobile-designer" — created
[support → archived-dept-old-x] #jkl012             — rejected: dept archived (410)
```

Формат строки:

```
[<requester_dept> → <target_dept>] #<task_id_short> "<title>" (<priority>) — <event>
```

Где `<event>` ∈ {
  `created`,
  `created (needs_approval)`,
  `approved-by-owner`,
  `rejected-by-owner: <reason>`,
  `modified-by-owner: priority <old>→<new>, labels <diff>`,
  `taken into queue, position N/M`,
  `counter-proposed: <field> <old>→<new>`,
  `priority-bumped-by-owner: <old>→<new>` (см. §2.7),
  `admin-override-by-owner`,
  `completed`,
  `cancelled: <reason>`,
  `rejected: dept archived` (410)
}.

**Immutability:** записи в этом канале **только append-only**. Никакой UI/API для удаления, никаких UPDATE кроме самого факта прихода нового event. Это закреплено в §6 (Безопасность).

Канал виден: owner'у — всё, Lead'ам — только записи с их участием (как requester или target). Rank-and-file роли его не видят (зачем — лишний контекст).

### 2.7. Owner возможности (escape hatch)

Owner — единственная роль, для которой действуют **обходные правила**:

#### Priority bump

Owner может на любой задаче (включая чужие cross-task) выполнить:

```
PATCH /api/tasks/<id>  {"priority_bump": true}
```

Эффект:

- priority задачи сдвигается на одну ступень вверх (P3→P2, P2→P1, P1→P1 c флагом `urgent=true`),
- в очереди target отдела задача переставляется в начало (или ближе к началу, согласно новой priority),
- audit пишет `priority-bumped-by-owner: P3→P2`.

Это нужно для случаев, когда owner видит что важный cross-task застрял в очереди по объективным причинам (другие задачи скопились), но бизнес-приоритет требует ускорения.

#### Admin override

Owner может создать cross-task **минуя Lead-канал**, напрямую направив задачу в любой отдел:

```
POST /api/departments/<target>/tasks
Body: {
  ...,
  "requester_department_id": null,    # owner — вне отделов
  "requester_role_slug": "owner",
  "admin_override": true
}
```

Это пропускает шаги 3 (skill-match), 4 (rate-limit), 5 (escalation gate) из §2.2 — owner сам себе авторизация. Используется в исключительных случаях (срочная инициатива, не вписывающаяся в обычный workflow). Audit пишет `admin-override-by-owner`.

Эти два механизма — **escape hatch**, не обычный режим работы. В UI owner'а они вынесены отдельной кнопкой («Force», не «Approve»), чтобы случайно не нажать.

### 2.8. Скип-роль escape pathway

Сценарий: `marketing-lead` создаёт cross-task к `design`, но в design-отделе нет роли с нужным скиллом (например, `mobile-illustrator`). Step 3 в §2.2 возвращает:

```json
HTTP/1.1 409 Conflict
{
  "error": "no matching role in target department",
  "target_department_id": "design",
  "offer_create_role_via_hr": true,
  "suggested_role_spec": {
    "name_hint": "mobile-illustrator",
    "skills": ["mobile-design", "illustration", "figma"],
    "model_hint": "sonnet",
    "description_seed": "Mobile-focused illustrator for marketing banners"
  }
}
```

UI поведение на стороне sender Lead'а:

```
┌─ Skill mismatch ───────────────────────────────────────────┐
│  Чтобы выполнить «draw mobile banner» в отделе Design,     │
│  нужна роль mobile-illustrator (skills: mobile-design,     │
│  illustration, figma).                                     │
│                                                            │
│  Запустить HR pipeline для создания этой роли в Design?    │
│  ↓                                                         │
│  [ Запустить HR (запрос owner'у) ]   [ Отмена ]            │
└────────────────────────────────────────────────────────────┘
```

Если sender Lead жмёт «Запустить HR»:

1. Backend создаёт **отдельную HR-задачу** в отделе target (см. ADR-004 §x — HR pipeline), `priority = P2`, `status = needs_approval`.
2. Эта HR-задача попадает в Inbox owner'а как обычный needs_approval (§2.5).
3. Если owner approve → HR pipeline в target отделе создаёт роль (ADR-004), затем **исходная cross-task пересоздаётся автоматически** (статус: `todo`, попадает в Inbox target Lead'а).
4. Если owner reject — sender Lead получает push «cross-task cancelled: role mobile-illustrator declined by owner», audit `cancelled: HR-rejected`.

Это даёт чёткий выход из тупика skill-mismatch без необходимости «вручную ходить и просить owner'а».

## 3. Consequences

**Облегчает:**

- **Единый протокол cross-team.** Любая роль / Lead знают, что cross-task = `POST /api/departments/<target>/tasks`, всё остальное запрещено. Это сильно сокращает поверхность ошибок.
- **Аудитируемость.** Inter-department channel (§2.6) даёт полную историю «кто кого о чём попросил и что из этого вышло» — критично для post-mortem'ов P1.
- **Защита от хаоса cross-роль запросов.** Rank-and-file роль не может flood'ить чужой отдел — Lead'а можно обучить «нет», тогда как 20 рассыпанных ролей — нельзя.
- **Чёткий escape pathway.** Skill mismatch не превращается в задачу-зомби — есть формальный путь «создать роль через HR» (§2.8).
- **Капасити-сигнал без фантазий.** Position-based визуализация даёт честную картину загрузки, без ETA-обещаний от LLM.

**Риски:**

- **Deadlock: два Lead'а одновременно создают друг другу cross-task.** Возможен сценарий, когда `marketing-lead` ждёт от `design`, а `design-lead` параллельно ждёт от `marketing`, и оба остановились на «не возьму пока не сделают моё». Решение: **no-decline + counter-proposal** уже блокирует drama-circles — обе задачи попадают в очереди (никто не отказывается). Если очередь обоих Lead'ов растёт без прогресса — это видно owner'у в capacity view (§2.4), он может priority-bump'ить одну из задач. Технического deadlock'а в БД нет (задачи независимы).
- **Длинные очереди demotivate.** Если sender Lead видит «будешь 47-м в очереди» — может бросить попытку. Mitigation: owner override (§2.7) для критичных кейсов; long-term — owner осознанно расширяет target отдел (HR-задача на добавление ролей).
- **Accidental escalation.** Бот может ошибочно проставить label `requires_budget` и эскалировать тривиальную задачу owner'у; owner получит шум в Inbox. Mitigation: owner-side кнопка «Modify» (§2.5) позволяет за один клик понизить priority и approve.
- **Counter-proposal loop.** Sender и target Lead могут гонять counter-предложения туда-сюда. Mitigation: hard-limit «не более 3 counter-итераций на задачу» — после третьей backend автоматически эскалирует owner'у с full diff'ом (`status: needs_approval`, reason: `counter-loop limit`). Реализация — задача бэкенду (см. §8).
- **Single channel перегружается.** В большом отделе inter-department channel может стать шумным. Mitigation: канал — append-only лог, его читают через фильтрацию (по dept / по priority / по дате), а не как «чат». UI обязан давать фильтры (§9 frontend tasks).
- **Сложность для open-source-пользователей.** Контрибьютор, разворачивающий devboard «как стартап с 1 отделом», увидит слой cross-department API, который ему не нужен. Mitigation: если в БД ровно 1 active department — UI скрывает inter-department секции, API возвращает 400 «cross-department features require ≥2 departments».

## 4. Alternatives Considered

### 4.1. Free cross-team messaging

«Любая роль может писать любой другой роли через MCP chat / комментарии, без Lead-посредника». **Отвергнуто.**

Минусы: хаос (см. §1), нет audit trail на уровне task'ов (только в чате), нет приоритезации (каждая роль считает свою задачу важнее), невозможно построить capacity view (queue сущности нет — есть только разговор). Это режим v1.x, который ломается на 2+ отделах.

### 4.2. No cross-team work (изолированные отделы)

«Отделы — герметичны, никаких cross-task'ов; для cross-нужд owner сам ставит задачу руками». **Отвергнуто.**

Реальные кейсы (marketing просит дизайнера, support просит engineers, sales просит копирайтера) требуют постоянных cross-связей. Принудительная герметичность вынудит owner'а вручную перекладывать десятки задач в день — это противоречит идее «owner управляет стратегически, отделы — операционно».

### 4.3. ETA-based scheduling вместо position-based

«Показывать estimated completion time вместо позиции в очереди». **Отвергнуто** — см. §2.4. LLM не имеет статистики для предсказания ETA; фейковые числа портят доверие. Position-based — единственная честная метрика на текущем уровне зрелости системы.

### 4.4. Allow decline (target Lead может отказаться от cross-task)

«Дать target Lead'у кнопку Decline — отклонить задачу, если считает не свой профиль». **Отвергнуто.**

Минусы:

- Возвращает хаос: sender Lead не имеет гарантии, что задача будет выполнена, → ходит к owner'у жаловаться, → owner перекладывает вручную (см. §4.2).
- Decline-spiral: target Lead отказывает, sender Lead отказывает свой обратный запрос «в отместку», система превращается в политику.
- Owner создавал отдел с конкретными ролями и скиллами **осознанно** — это значит этот отдел берёт работу по своему профилю. Decline — это «передумываем» в обход owner'а.

**Counter-proposal даёт гибкость без выхода из системы.** Target Lead может: предложить более низкий приоритет, изменить scope, попросить отложить. Sender Lead может согласиться (audit пишет `counter-accepted`) или эскалировать owner'у (§2.5). Все варианты остаются внутри audit trail.

Skill-mismatch (то, что обычно мотивирует «дайте decline») закрывается через §2.8 — формальный путь через HR pipeline.

### 4.5. Generic ticket-system (Jira-like) с workflow-engine

«Взять готовый Jira/Linear-style ticket-flow с состояниями, transitions, SLA». **Отвергнуто.**

Это full-blown PM-tool, который добавит десятки сущностей (sprints, epics-as-entity, custom-fields, permissions matrix). YAGNI — нам нужно ровно три типа событий (create / counter / complete) и линейная priority. Своя минимальная реализация ближе к 200 строк бэкенд-кода, чем к интеграции внешнего ticket-system.

## 5. Edge cases

### 5.1. Concurrent deadlock (оба Lead'а создают cross-task друг к другу одновременно)

Описание: в одну и ту же миллисекунду `marketing-lead` делает `POST /api/departments/design/tasks`, и `design-lead` — `POST /api/departments/marketing/tasks`.

**Решение:** на уровне БД обе задачи проходят без проблем (нет общего lock'а). На уровне UX никакого deadlock'а нет — каждая задача попадает в свою очередь независимо. Lead'ы видят их параллельно в своих Inbox'ах и принимают независимые решения о порядке выполнения.

Если же в логике проявится race (например при skill-match через одну и ту же роль) — backend использует `SERIALIZABLE` транзакции для шагов 2-6 §2.2; конфликт повторяется retry'ем с jitter.

### 5.2. HR создаёт новую роль в процессе обработки cross-task (race condition)

Сценарий: sender Lead запустил HR pipeline через §2.8; параллельно target Lead вручную через ADR-004 создал ту же самую роль с похожими скиллами. Когда HR pipeline доходит до создания — роль уже есть.

**Решение:** HR pipeline (ADR-004) проверяет `EXISTS(SELECT 1 FROM roles WHERE department_id = ... AND skills ⊇ <required>)` непосредственно перед `INSERT`. Если уже есть — пропускает создание, переходит сразу к шагу «пересоздать исходный cross-task с найденной ролью», audit пишет `HR: role already existed, skipped creation`.

### 5.3. Цепочка inter-department: A→B→C

Сценарий: `marketing-lead` создаёт задачу для `engineering` («deploy landing»); `engineering-lead` обнаруживает, что для деплоя нужна работа `design` («provide final SVG assets») — он сам делает cross-task `engineering → design`.

**Решение:** цепочка работает **рекурсивно по тому же протоколу**. Поле `requester_role_slug` для второй задачи = `engineering-lead`, `requester_department_id = engineering`. Audit-канал (§2.6) показывает обе записи независимо, читатель легко связывает их по комментариям к исходной задаче.

Никакого специального dependency-tracking на уровне cross-task'ов **не вводим** (YAGNI). Если sender хочет показать зависимость — использует обычный `add_dependency` (ADR-003), который работает и для cross-задач. Циклические зависимости (A→B→A) ловятся существующим check'ом cycle-detection в `add_dependency`.

### 5.4. Cross-task в архивированный отдел

Сценарий: owner архивировал отдел `legacy-x`. После этого `marketing-lead` пытается создать к нему cross-task (например, не обновил локальный список).

**Решение:** step 2 §2.2 возвращает HTTP `410 Gone` с `{"error": "target department archived"}`. UI sender Lead'а показывает понятное сообщение «Отдел Legacy-X архивирован — задача не создана». Audit пишет `rejected: dept archived`. Sender может пересоздать в актуальный отдел или отложить.

### 5.5. Counter-proposal loop (≥3 итераций)

Уже описано в §3 (Риски). Hard-limit 3 итерации; при превышении — автоэскалация owner'у с full diff'ом.

### 5.6. Owner archival of his own admin-override task

Сценарий: owner создал задачу через admin-override (§2.7), потом передумал и архивирует отдел target. **Решение:** существующая логика архивации отдела (ADR-003) обрабатывает все его задачи единообразно (cancel/archive); admin-override-флаг не даёт никакой privileged-обработки в этом case.

## 6. Безопасность

### 6.1. Rate-limit на cross-task creation

Лимит: **10 задач priority P3 за 24 часа на пару (requester_department → target_department)**.

Обоснование числа: предполагаемая «нормальная» нагрузка — 2-3 cross-task'а в день на пару отделов; 10 — это 3-4x margin для пиков. Заведомо выше реалистичного объёма, но достаточно низко, чтобы поймать broken-loop (бот в Lead'е циклически генерирует задачи из-за ошибки prompting).

Задачи priority P1/P2 **не лимитируются** — у них уже есть гейт через `needs_approval` (§2.2 step 5), который ограничивает спам через owner'а.

Реализация — middleware на endpoint POST /api/departments/<id>/tasks; storage счётчика — Redis (если есть) или таблица `rate_limit_events` (если нет). При превышении → 429 + `reset_at` header.

### 6.2. AuthZ на создание cross-task

Шаг 1 §2.2: caller должен иметь role.name ∈ {`<requester_dept>-lead`, `owner`}.

Реализация: middleware читает session → role → name. Соответствие с frontmatter (ADR-002 §2.2) гарантировано загрузчиком ролей. Любая другая роль (rank-and-file) получает 403.

Дополнительно: rank-and-file роли по умолчанию **не имеют MCP-tool'а `mcp__devboard-tasks__create_task` с `department_id != своего`** — это закрывается на стороне MCP-сервера через проверку `task.department_id == role.department_id OR role.name == 'owner'` (см. tasks §8). Это второй слой защиты — даже если кто-то обойдёт REST, MCP не пропустит.

### 6.3. Audit log immutable

Записи в inter-department channel (§2.6) хранятся в таблице с триггером, запрещающим UPDATE/DELETE:

```sql
CREATE TABLE inter_department_events (
    id SERIAL PRIMARY KEY,
    task_id TEXT NOT NULL,
    requester_department_id TEXT,
    target_department_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE RULE no_update AS ON UPDATE TO inter_department_events DO INSTEAD NOTHING;
CREATE RULE no_delete AS ON DELETE TO inter_department_events DO INSTEAD NOTHING;
```

(SQLite-эквивалент — триггеры `BEFORE UPDATE/DELETE ... RAISE FAIL`.)

Это гарантирует, что даже бэкенд-bug или sloppy SQL-патч не сотрёт audit trail.

### 6.4. PII / sensitive data

Cross-task description может содержать любую строку — это пользовательский ввод. Запрета на содержимое мы не вводим (это не наша задача), но требуем: при логировании в inter-department channel **не дублируем description полностью** — только title и priority. Полное содержимое доступно только при открытии самой задачи через её endpoint (с обычной AuthZ). Это снижает риск утечки sensitive-данных через audit-feed, который читают шире чем саму задачу.

## 7. Migration plan

### 7.1. SQL миграция

Двумя ALTER'ами (см. §2.1) + создание индекса + создание таблицы `inter_department_events`.

Для старых задач v1.x (intra-моно-команда): `requester_department_id` ставится в `NULL`, что корректно — это intra-department. Никакого back-fill'а не требуется.

### 7.2. Endpoint логика

Реализация `POST /api/departments/<target_id>/tasks` (§2.2) в `mcp_server` и `dashboard/app.py`. Существующий `create_task` (MCP) обогащается проверкой §6.2 (запрет на `department_id != своего` для rank-and-file).

### 7.3. UI

Inbox-секции (§2.3, §2.5), capacity badges (§2.4), counter-proposal modal — отдельная задача frontend'у (см. §9).

### 7.4. Обратная совместимость

- Задачи без `requester_department_id` (legacy v1.x) — работают как intra-department, никаких изменений в их UI.
- Старый endpoint `POST /api/tasks` (без `department_id` в URL) — продолжает работать для intra-задач, не лезет в inter-department логику. Это нужно, чтобы не сломать существующий код subagent'ов.

### 7.5. Roll-out

В рамках milestone v2.0, **после** мерджа ADR-003 и ADR-004. Если v2.0 откладывается — эта ADR остаётся `Proposed` и не блокирует другие работы (только intra-моно-команда v1.x пока работает).

## 8. Tasks для бэкенда

| ID (заводится позже) | Что | Зависит от |
|---|---|---|
| **B1** | SQL миграция: 2 ALTER на `tasks` (§2.1) + индекс + таблица `inter_department_events` с триггерами immutability | ADR-003 |
| **B2** | REST endpoint `POST /api/departments/<id>/tasks` со всеми 6 шагами pipeline'а (§2.2) | B1 |
| **B3** | Endpoint `GET /api/departments/<id>/queue-position-preview` (§2.4) | B1 |
| **B4** | Endpoint `PATCH /api/tasks/<id>` с поддержкой `counter_proposal`, `priority_bump`, `admin_override` | B2 |
| **B5** | Rate-limit middleware (§6.1) — 10 P3 / 24h / dept-pair, storage в Redis или `rate_limit_events` | B2 |
| **B6** | Counter-proposal loop limit (3 итерации → auto-escalate owner'у, см. §3 риски) | B4 |
| **B7** | Cross-task event logger → `inter_department_events` для всех событий из §2.6 | B1, B2 |
| **B8** | Owner override endpoints: priority bump + admin override (§2.7) | B4 |
| **B9** | Skill-match logic для step 3 §2.2 + 409-ответ с `suggested_role_spec` (§2.8) | B2, ADR-004 |
| **B10** | Integration с HR pipeline (ADR-004): при approve owner'ом HR-задачи → автопересоздание исходного cross-task | B9, ADR-004 |
| **B11** | MCP-server: запрет на `create_task` с `department_id != своего` для не-Lead не-owner ролей (второй слой защиты §6.2) | B1 |
| **B12** | Архив-check: вернуть 410 Gone при cross-task в `archived` отдел (§5.4) | B2 |

**Итого: 12 задач бэкенду.**

## 9. Tasks для frontend

| ID | Что |
|---|---|
| **F1** | Inbox section «Inter-department requests» в дашборде target Lead'а (§2.3): карточки, цвет origin, кнопки Take/Counter |
| **F2** | Inbox section «Department requests» в дашборде owner'а (§2.5): карточки, кнопки Approve/Reject/Modify |
| **F3** | Sidebar capacity badges `(N в работе, M в очереди)` для всех отделов (§2.4), hover-popup с position-листом |
| **F4** | Modal «Create cross-task» с position-preview (§2.4) |
| **F5** | Counter-proposal modal (§2.3): UI для priority/scope counter'а |
| **F6** | Skill-mismatch dialog (§2.8): «запустить HR pipeline?» с suggested_role_spec |
| **F7** | Inter-department channel viewer (§2.6) с фильтрами (dept / priority / date), append-only timeline |
| **F8** | Owner-only «Force» button (priority bump + admin override) с подтверждением (§2.7) |
| **F9** | UI guard: если active departments == 1 → скрыть inter-department секции, показать hint «cross-department features activate at 2+ departments» (§3 риски) |

**Итого: 9 задач frontend'у.**

## 10. Tasks для QA

| ID | Что |
|---|---|
| **Q1** | Happy path: `marketing-lead` создаёт P3 cross-task для `design`, target Lead жмёт «Take into queue», задача появляется в queue с corerct position. Audit пишет `created` + `taken into queue, position N/M`. |
| **Q2** | AuthZ 403: rank-and-file роль (например `marketing-copywriter`) пытается POST /api/departments/design/tasks → 403 с понятным error-message |
| **Q3** | Skill-mismatch 409: cross-task с labels, не покрытыми ролями target → 409 с `offer_create_role_via_hr: true` и заполненным `suggested_role_spec` |
| **Q4** | Rate-limit smoke: подряд 11 P3-задач от одного и того же sender→target за 24h, 11-я отклоняется с 429 + `reset_at` |
| **Q5** | Escalation P1: создаём P1 cross-task → статус `needs_approval`, появляется в Inbox owner'а; approve → переходит в Inbox target Lead'а |
| **Q6** | Counter-proposal loop limit: 3 counter-итерации подряд → 4-я автоэскалирует owner'у со статусом `needs_approval` |
| **Q7** | Concurrent deadlock test: одновременно (через 2 потока) `A-lead → B` и `B-lead → A`; обе задачи создаются успешно, никаких deadlock'ов |
| **Q8** | Archived dept: cross-task в `archived` отдел → 410 Gone, audit пишет `rejected: dept archived` |
| **Q9** | Owner override: owner делает priority-bump на чужой cross-task → задача сдвигается в начало очереди target, audit пишет `priority-bumped-by-owner` |
| **Q10** | HR escape pathway end-to-end: skill-mismatch → запуск HR-задачи → owner approve → создание роли → автопересоздание исходного cross-task (см. §2.8 + §5.2) |
| **Q11** | Audit log immutability: попытка UPDATE/DELETE в `inter_department_events` через прямой SQL → отвергается триггером |
| **Q12** | Single-department UI guard: при `active_departments == 1` inter-department секции скрыты во всех Inbox'ах |

**Итого: 12 задач QA.**

## 11. Зависимости

- **ADR-003** (`docs/adr/0003-departments.md`) — требуется модель `departments` (id, status, color, roles) и колонка `tasks.department_id`. Этот ADR расширяет схему `tasks` (§2.1), но не меняет ADR-003.
- **ADR-004** (`docs/adr/0004-hr-role.md`) — требуется HR-роль и pipeline создания новых ролей в отделе для escape pathway §2.8. Без ADR-004 §2.8 деградирует до «вернуть 409 с человеко-читаемым сообщением, owner создаёт роль вручную».
- **ADR-002** (`docs/adr/0002-role-format.md`) — `name` ролей используется в `requester_role_slug`; `tools`-allowlist Lead'ов должен включать cross-task endpoints.
- **ADR-001** (`docs/adr/0001-llm-provider.md`) — нет прямой зависимости; cross-task протокол работает независимо от выбранного LLM-провайдера каждой роли.

## 12. Open questions

### 12.1. Priority внутри одной P-категории

Когда в очереди target отдела 5 задач P3 — их порядок чисто по `created_at`? Или нужен sub-priority внутри P3? **Текущее предложение:** только `created_at`. Если когда-нибудь выявится, что внутри P3 нужны «срочнее» и «не срочнее» — отдельная ADR с введением P3-high / P3-low или числовой weight'ом.

### 12.2. Что считается «destructive» labels

Labels `requires_budget` и `destructive` триггерят escalation gate (§2.2 step 5). Их конкретный список — пока soft (каждый Lead сам ставит). Если выявится разнобой — отдельный реестр labels в ADR-003-rev или в коде.

### 12.3. Уведомления sender Lead'у о completion

Сейчас sender Lead узнаёт о завершении cross-task через audit-channel + (опционально) через push в Inbox. Стоит ли давать ему дополнительный canonical-сигнал (например, mark complete-cross-task badge в его Inbox)? **Текущее предложение** — пока нет, audit-канала + общего push достаточно. Если пользовательский фидбэк скажет «теряюсь» — добавим Inbox-секцию «My outgoing cross-tasks» отдельной задачей.

## 13. References

- ADR-001 — `docs/adr/0001-llm-provider.md` (LLM-провайдеры — не пересекается напрямую с этим ADR)
- ADR-002 — `docs/adr/0002-role-format.md` (`name`, `tools` ролей)
- ADR-003 — `docs/adr/0003-departments.md` (модель `departments`, `tasks.department_id`)
- ADR-004 — `docs/adr/0004-hr-role.md` (HR-роль, pipeline создания новых ролей)
- Inter-department parent task — `d673a1d6c156`
- Roles definition — `roles/архитектор.md` (принципы YAGNI, composition>inheritance)

## Changelog

- **2026-05-22:** Initial draft (Proposed) — задача `d673a1d6c156`. Все решения owner'а формализованы; depends_on ADR-003 + ADR-004 (оба в процессе).

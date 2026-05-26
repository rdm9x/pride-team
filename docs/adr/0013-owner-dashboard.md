# ADR-013 — Owner Dashboard (проекты + статусы + CTA)

- **Status:** Proposed (2026-05-25)
- **Date:** 2026-05-25
- **Authors:** Claude-сессия (Haiku 4.5) совместно с архитектором
- **Task:** `#02215A903F04` (Owner Dashboard redesign)
- **Epic:** Phase 2.0 — Owner-focused UI + workspace management
- **Supersedes:** —
- **Depends on:**
  - **ADR-010** (`0010-workspace-artifacts.md`) — source данных: `task_artifacts` таблица, `project_slug` метаданные.
  - **ADR-011** (`0011-chat-threads-planning.md`) — chat integration в правую панель (или отдельный modal).
- **Related:**
  - **Phase 2.0 эпик** — B1, B2 (backend), F3, F4 (frontend).

---

## 1. Context

### 1.1. Owner-проблема (2026-05-25)

Owner сказал: **«Куда смотреть, где результат, как понять что готово — не понимаю»**.

Текущее состояние:
- Главная (`/`) — Kanban доска 5 колонок (todo, wip, needs_approval, review, done).
- Owner видит **269 задач** со всех отделов и проектов в одной плоскости.
- Нет группировки по проектам (workspace/landing-outdoor/, workspace/marketing-site-v2/ и т.д.).
- Нет быстрого понимания:
  - *«Что готово на проект X?»* — надо искать руками в доске.
  - *«Какие задачи ждут запуска/одобрения на Y?»* — нет call-to-actions.
  - *«Где файлы результатов?»* — нет ссылок на workspace/.
- Chat в узкой правой панели нечитаем (ADR-011).

### 1.2. Текущая архитектура (что есть)

- **ADR-010**: `task_artifacts` таблица + `project_slug` из path `workspace/project-slug/task-id/file`.
- **ADR-011**: `/chat` полностраничный интерфейс планёрок и обсуждений (Phase 3).
- **Kanban** в `/` — 5-колончатая доска (todo/wip/needs_approval/review/done).
- Sidebar: пункты навигации (Доска, Inbox, Статистика, Роли, Архив).

### 1.3. Требование (видение 2026-05-25)

> *«Главная страница: карточки по проектам. На каждой карточке:*
> - *Прогресс (готово 3, в работе 2, ждёт 1).*
> - *Кнопки для owner-а: [Принять задачу #X], [Запустить роль Y], [Открыть папку].*
> - *Одна кнопка — один action. Не нужно ходить по 5 вкладкам.»*

---

## 2. Decision

### 2.1. Макет главной страницы `/`

**Новая главная** заменяет текущий Kanban:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Devboard → Owner Dashboard                             💬 [Показать чат] │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  🏘 ПРОЕКТЫ (группировка по project_slug из workspace/)                     │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  📦 landing-outdoor-2026                                             │   │
│  │  ════════════════════════════════════════════════════════════════    │   │
│  │  3 готово · 2 в работе · 1 ждёт  [████░░░░] 60%                     │   │
│  │                                                                      │   │
│  │  📋 Review (1):                                                      │   │
│  │    ☐ (#a1b2c3) Лендинг HTML → [Принять] [Отклонить]               │   │
│  │                                                                      │   │
│  │  ⏸ Ждёт запуска (2):                                                │   │
│  │    ☐ (#d4e5f6) Тесты SEO (role=qa)  → [▶ Запустить QA]            │   │
│  │    ☐ (#g7h8i9) Деплой (role=devops)  → [▶ Запустить Devops]       │   │
│  │                                                                      │   │
│  │  🚨 Blocked (1):                                                     │   │
│  │    ☐ (#j0k1l2) Копирайт     [Ждёт] Пока не закончена дизайн      │   │
│  │                      → [Разблокировать] [Открыть детали]            │   │
│  │                                                                      │   │
│  │  🔗 Файлы (3):                                                       │   │
│  │    📄 landing.html  · 🎨 style.css  · 📊 seo-report.pdf             │   │
│  │    → [📂 Открыть папку workspace/landing-outdoor-2026/]            │   │
│  │                                                                      │   │
│  │  [💬 История проекта]  [🔄 Обновить статусы]  [⋯ Ещё]              │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  📦 marketing-site-v2                                                │   │
│  │  ════════════════════════════════════════════════════════════════    │   │
│  │  5 готово · 0 в работе · 0 ждёт  [████████░] 100%  ✅ ЗАВЕРШЕНО     │   │
│  │  → [▼ Свернуть детали]                                              │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  📦 [Без проекта]  (Devboard internal Phase X.Y)                     │   │
│  │  ════════════════════════════════════════════════════════════════    │   │
│  │  2 готово · 3 в работе  [███░░░░░░] 40%                             │   │
│  │  → [Развернуть]                                                      │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  [Архив] [Статистика] [Доска (Kanban)] [Inbox]                             │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Структура карточки-проекта:**

1. **Заголовок** — `project_slug` (или title первой задачи в проекте).
2. **Прогресс** (одна строка):
   - Счётчики: `N готово`, `M в работе`, `K ждёт`.
   - Визуальная полоса прогресса: `[████░░░░]` (заполнение `done / (done+wip+todo)`).
   - Процент: `60%`.
3. **Секции action items** (если есть):
   - **📋 Review (N)** — задачи со статусом `needs_approval` или `review`.
     - Inline-кнопки: `[Принять]`, `[Отклонить]`, `[Комментарий]`.
   - **⏸ Ждёт запуска (M)** — задачи со статусом `todo` (никогда не запускались).
     - Inline-кнопки: `[▶ Запустить <role>]` (роль берётся из `task.assignee`).
   - **🚨 Blocked (K)** — задачи со статусом `blocked`.
     - Краткая причина (из `task.comment` или сообщение блокировки).
     - Кнопка: `[Разблокировать]`, `[Открыть детали]`.
4. **Файлы** — список артефактов (если есть в `task_artifacts`).
   - Иконки по MIME-типу (📄 текст, 🎨 изображение, 📊 документ).
   - Кнопка: `[📂 Открыть папку]` (локально или скачать).
5. **Ниже карточки** — footer-кнопки:
   - `[💬 История проекта]` → открывает thread в чате (ADR-011).
   - `[🔄 Обновить статусы]` → рефреш из БД.
   - `[⋯ Ещё]` → dropdown (архивировать проект, экспорт и т.д.).

### 2.2. Data Model

#### 2.2.1. Вычисляемые свойства проекта (на backend)

```python
class ProjectCard:
    project_slug: str                    # из workspace path или tasks.project_slug
    title: str                           # первый title в проекте, если нет явного
    status: str                          # 'active' | 'completed' | 'blocked'
    progress: dict = {
        'done': int,                     # count tasks со статусом done
        'in_review': int,                # count tasks со статусом review + needs_approval
        'in_progress': int,              # count tasks со статусом wip
        'todo': int,                     # count tasks со статусом todo
        'blocked': int,                  # count tasks со статусом blocked
        'total': int,
        'percentage': float,             # (done / total) * 100
    }
    
    action_items: dict = {
        'review': List[TaskPreview],     # needs_approval, review
        'waiting_to_start': List[TaskPreview],  # todo не запускались
        'blocked': List[TaskPreview],    # blocked
    }
    
    artifacts: List[dict] = [            # из task_artifacts
        {
            'id': int,
            'file_path': str,
            'task_id': str,
            'kind': str,                  # 'file' | 'folder'
            'mime_type': str,             # application/pdf, image/png, text/html
            'size_bytes': int,
        }
    ]
    
    last_updated_at: int                # timestamp последнего изменения задачи в проекте
    workspace_path: str                  # абсолютный путь /Users/.../workspace/project-slug/
```

#### 2.2.2. TaskPreview (краткая информация задачи)

```python
class TaskPreview:
    id: str                              # task.id (12 hex)
    title: str
    status: str                          # current status
    assignee: str                        # role_slug (тимлид, разработка, qa, etc.)
    department_id: str
    labels: List[str]
    blocking_reason: Optional[str]       # для blocked: почему заблокирована
    parent_id: Optional[str]             # если cross-dept
```

### 2.3. REST API endpoints (backend)

#### 2.3.1. `GET /api/projects`

Получить все проекты (группировка от backend).

**Запрос:**

```
GET /api/projects?include_archived=false&include_devboard=true
```

**Параметры:**
- `include_archived` (bool, default false) — включить завершённые проекты.
- `include_devboard` (bool, default true) — включить специальную группу «Без проекта» (Devboard Phase).

**Ответ (200 OK):**

```json
{
  "status": "ok",
  "projects": [
    {
      "project_slug": "landing-outdoor-2026",
      "title": "Лендинг outdoor billboards",
      "status": "active",
      "progress": {
        "done": 3,
        "in_review": 1,
        "in_progress": 2,
        "todo": 0,
        "blocked": 1,
        "total": 7,
        "percentage": 42.8
      },
      "action_items": {
        "review": [
          {
            "id": "a1b2c3d4e5f6",
            "title": "Лендинг HTML",
            "status": "needs_approval",
            "assignee": "frontend",
            "department_id": "разработка"
          }
        ],
        "waiting_to_start": [
          {
            "id": "d4e5f6g7h8i9",
            "title": "Тесты SEO",
            "status": "todo",
            "assignee": "qa",
            "department_id": "qa"
          },
          {
            "id": "j0k1l2m3n4o5",
            "title": "Деплой",
            "status": "todo",
            "assignee": "devops",
            "department_id": "devops"
          }
        ],
        "blocked": [
          {
            "id": "p6q7r8s9t0u1",
            "title": "Копирайт",
            "status": "blocked",
            "assignee": "marketing",
            "department_id": "маркетинг",
            "blocking_reason": "Ждёт завершения дизайна (#f7g8h9)"
          }
        ]
      },
      "artifacts": [
        {
          "id": 42,
          "file_path": "workspace/landing-outdoor-2026/a1b2c3d4e5f6/landing.html",
          "task_id": "a1b2c3d4e5f6",
          "kind": "file",
          "mime_type": "text/html",
          "size_bytes": 15234
        },
        {
          "id": 43,
          "file_path": "workspace/landing-outdoor-2026/a1b2c3d4e5f6/style.css",
          "task_id": "a1b2c3d4e5f6",
          "kind": "file",
          "mime_type": "text/css",
          "size_bytes": 3421
        }
      ],
      "last_updated_at": 1716669600,
      "workspace_path": "/Users/dm_pc/Desktop/pride-team-v1.0/workspace/landing-outdoor-2026"
    },
    {
      "project_slug": "marketing-site-v2",
      "title": "Маркетинг сайт V2",
      "status": "completed",
      "progress": {
        "done": 5,
        "in_review": 0,
        "in_progress": 0,
        "todo": 0,
        "blocked": 0,
        "total": 5,
        "percentage": 100.0
      },
      "action_items": {
        "review": [],
        "waiting_to_start": [],
        "blocked": []
      },
      "artifacts": [],
      "last_updated_at": 1716658800,
      "workspace_path": "/Users/dm_pc/Desktop/pride-team-v1.0/workspace/marketing-site-v2"
    }
  ],
  "devboard_tasks": {
    "project_slug": "[Без проекта]",
    "title": "Devboard: Phase 2.0",
    "status": "active",
    "progress": {
      "done": 2,
      "in_review": 0,
      "in_progress": 3,
      "todo": 5,
      "blocked": 0,
      "total": 10,
      "percentage": 20.0
    },
    "action_items": { /* аналогично */ },
    "artifacts": [],
    "last_updated_at": 1716654000
  }
}
```

#### 2.3.2. `GET /api/projects/<project_slug>`

Получить детали одного проекта с full-thread из чата.

**Запрос:**

```
GET /api/projects/landing-outdoor-2026
```

**Ответ (200 OK):**

```json
{
  "status": "ok",
  "project": { /* как в /api/projects, но полный набор задач */ },
  "chat_thread": {
    "id": "thread-abc123",
    "title": "Лендинг outdoor billboards",
    "kind": "planning",
    "messages": [
      {
        "id": "msg1",
        "author": "owner",
        "text": "Нужно сделать лендинг...",
        "created_at": 1716600000
      },
      {
        "id": "msg2",
        "author": "managing-director",
        "text": "Начнём с фронтенда...",
        "created_at": 1716601000
      }
    ],
    "status": "finished",
    "decision_summary": "Решение: фронтенд + тесты + деплой"
  }
}
```

#### 2.3.3. `POST /api/projects/<project_slug>/accept-task`

Owner принимает (одобряет) задачу в статусе `needs_approval` → переводит в `done`.

**Запрос:**

```json
POST /api/projects/landing-outdoor-2026/accept-task
{
  "task_id": "a1b2c3d4e5f6",
  "comment": "Выглядит хорошо"
}
```

**Ответ (200 OK):**

```json
{
  "status": "ok",
  "task_id": "a1b2c3d4e5f6",
  "new_status": "done"
}
```

#### 2.3.4. `POST /api/projects/<project_slug>/start-task`

Owner запускает задачу со статусом `todo` → переводит в `wip`.

**Запрос:**

```json
POST /api/projects/landing-outdoor-2026/start-task
{
  "task_id": "d4e5f6g7h8i9",
  "role": "qa"
}
```

**Ответ (200 OK):**

```json
{
  "status": "ok",
  "task_id": "d4e5f6g7h8i9",
  "new_status": "wip",
  "session_started_at": 1716670000
}
```

#### 2.3.5. `POST /api/projects/<project_slug>/unblock`

Owner разблокирует задачу → переводит в `todo` и добавляет комментарий.

**Запрос:**

```json
POST /api/projects/landing-outdoor-2026/unblock
{
  "task_id": "p6q7r8s9t0u1",
  "reason": "Дизайн завершён, можно делать копирайт"
}
```

**Ответ (200 OK):**

```json
{
  "status": "ok",
  "task_id": "p6q7r8s9t0u1",
  "new_status": "todo"
}
```

#### 2.3.6. `POST /api/open-folder`

Открыть workspace-папку проекта локально (macOS: `open`, Linux: `xdg-open`, Windows: `os.startfile`).

**Запрос:**

```json
POST /api/open-folder
{
  "path": "/Users/dm_pc/Desktop/pride-team-v1.0/workspace/landing-outdoor-2026"
}
```

**Ответ (200 OK):**

```json
{
  "status": "opened",
  "path": "/Users/dm_pc/Desktop/pride-team-v1.0/workspace/landing-outdoor-2026"
}
```

### 2.4. Frontend компоненты

#### 2.4.1. Главная страница `/` (Owner Dashboard)

**Путь:** `dashboard/templates/owner-dashboard.html` (новая)

**Struktur:**

```html
<!-- Topbar (как сейчас) -->
<header class="topbar">
  <button id="btn-chat-toggle">💬 Показать чат (сокращённо) / 💬 Скрыть</button>
  <button id="btn-nav-board">Доска (Kanban)</button>
  <!-- ... -->
</header>

<!-- Main container -->
<main class="owner-dashboard">
  <!-- Projects grid -->
  <div class="projects-container">
    <!-- Карточка проекта (компонента) -->
  </div>
</main>

<!-- Sidebar чата (опционально, ADR-011) -->
<aside class="chat-sidebar" id="chat-sidebar" hidden>
  <!-- Краткая история thread-а или inline-комментарии -->
</aside>
```

**JavaScript компонент** `dashboard/static/app.js` (новый модуль или расширение):

```javascript
// Fetch projects
async function loadProjects(includeArchived = false) {
  const resp = await fetch(`/api/projects?include_archived=${includeArchived}`);
  const data = await resp.json();
  renderProjects(data.projects, data.devboard_tasks);
}

// Render project card
function renderProjectCard(project) {
  const card = document.createElement('div');
  card.className = 'project-card';
  card.innerHTML = `
    <header class="project-header">
      <h2>${escapeHtml(project.title)}</h2>
      <span class="progress-badges">
        ${project.progress.done} готово · 
        ${project.progress.in_progress} в работе · 
        ${project.progress.todo + project.progress.blocked} ждёт
      </span>
    </header>
    
    <div class="progress-bar">
      <div class="bar" style="width: ${project.progress.percentage}%"></div>
      <span>${project.progress.percentage.toFixed(1)}%</span>
    </div>
    
    ${renderActionItems(project.action_items)}
    ${renderArtifacts(project.artifacts)}
    
    <footer class="project-footer">
      <button class="btn-project-history">💬 История</button>
      <button class="btn-project-refresh">🔄 Обновить</button>
      <button class="btn-project-more">⋯ Ещё</button>
    </footer>
  `;
  return card;
}

// Render action items (review, waiting, blocked)
function renderActionItems(items) {
  let html = '';
  
  if (items.review?.length) {
    html += `<section class="action-section review">
      <h3>📋 Review (${items.review.length})</h3>
      ${items.review.map(task => `
        <div class="action-item">
          <span>#${task.id.slice(0, 8)}</span>
          <span>${task.title}</span>
          <button class="btn-accept" data-task-id="${task.id}">Принять</button>
        </div>
      `).join('')}
    </section>`;
  }
  
  if (items.waiting_to_start?.length) {
    html += `<section class="action-section waiting">
      <h3>⏸ Ждёт запуска (${items.waiting_to_start.length})</h3>
      ${items.waiting_to_start.map(task => `
        <div class="action-item">
          <span>#${task.id.slice(0, 8)}</span>
          <span>${task.title} (${task.assignee})</span>
          <button class="btn-start" data-task-id="${task.id}" data-role="${task.assignee}">
            ▶ Запустить ${task.assignee}
          </button>
        </div>
      `).join('')}
    </section>`;
  }
  
  if (items.blocked?.length) {
    html += `<section class="action-section blocked">
      <h3>🚨 Blocked (${items.blocked.length})</h3>
      ${items.blocked.map(task => `
        <div class="action-item">
          <span>#${task.id.slice(0, 8)}</span>
          <span>${task.title}</span>
          <span class="reason">${task.blocking_reason || 'Причина неизвестна'}</span>
          <button class="btn-unblock" data-task-id="${task.id}">Разблокировать</button>
        </div>
      `).join('')}
    </section>`;
  }
  
  return html;
}
```

**Стили** `dashboard/static/css/owner-dashboard.css` (новый):

```css
.owner-dashboard {
  display: grid;
  grid-template-columns: 1fr;
  gap: 2rem;
  padding: 2rem;
}

.projects-container {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.project-card {
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 1.5rem;
  background: var(--color-card-bg);
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
}

.project-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
  gap: 1rem;
}

.project-header h2 {
  margin: 0;
  font-size: 1.25rem;
}

.progress-bar {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 1rem;
}

.progress-bar .bar {
  flex: 1;
  height: 8px;
  background: var(--color-progress-bg);
  border-radius: 4px;
  overflow: hidden;
}

.progress-bar .bar > div {
  height: 100%;
  background: var(--color-progress-fill);
  transition: width 0.3s ease;
}

.action-section {
  margin: 1rem 0;
  padding: 0.75rem;
  background: var(--color-section-bg);
  border-left: 3px solid var(--color-section-accent);
  border-radius: 4px;
}

.action-section h3 {
  margin: 0 0 0.75rem 0;
  font-size: 0.95rem;
  font-weight: 600;
}

.action-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  padding: 0.5rem 0;
  border-bottom: 1px solid var(--color-border-light);
}

.action-item:last-child {
  border-bottom: none;
}

.action-item button {
  flex-shrink: 0;
  padding: 0.35rem 0.75rem;
  font-size: 0.85rem;
  border-radius: 4px;
  cursor: pointer;
  white-space: nowrap;
}

.btn-accept {
  background: var(--color-accept);
  color: white;
}

.btn-start {
  background: var(--color-play);
  color: white;
}

.btn-unblock {
  background: var(--color-warning);
  color: white;
}

.project-footer {
  display: flex;
  gap: 0.5rem;
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid var(--color-border);
}

.project-footer button {
  flex: 1;
  padding: 0.5rem;
  border-radius: 4px;
  border: 1px solid var(--color-border);
  background: transparent;
  cursor: pointer;
  font-size: 0.85rem;
}

.project-footer button:hover {
  background: var(--color-hover);
}

/* Artifacts section */
.artifacts-section {
  margin: 1rem 0;
  padding: 0.75rem;
  background: var(--color-artifacts-bg);
  border-radius: 4px;
}

.artifacts-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.artifact-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.35rem 0.65rem;
  background: var(--color-chip-bg);
  border-radius: 3px;
  font-size: 0.8rem;
  cursor: pointer;
}

.artifact-chip:hover {
  background: var(--color-chip-hover);
}
```

### 2.5. Sidebar навигация

**Изменения в `dashboard/templates/kanban.html`:**

```html
<!-- Текущая структура сохраняется, но главная вьюшка переключается -->

<nav class="nav">
  <!-- NEW: Dashboard как главная -->
  <button class="nav-item active" data-view="dashboard">
    <span class="ico">📊</span>
    <span class="lbl">Owner Dashboard</span>
  </button>
  
  <!-- Старая Doska теперь вторая -->
  <button class="nav-item" data-view="board">
    <span class="ico">🗂</span>
    <span class="lbl">Доска (Kanban)</span>
  </button>
  
  <!-- Остальное -->
  <button class="nav-item" id="btn-nav-chat">
    <span class="ico">💬</span>
    <span class="lbl">Чат</span>
  </button>
  <!-- ... -->
</nav>
```

**JavaScript переключение views:**

```javascript
// Вместо текущего кода переключения вьюшек
document.querySelectorAll('[data-view]').forEach(btn => {
  btn.addEventListener('click', (e) => {
    const view = e.currentTarget.dataset.view;
    showView(view);
  });
});

function showView(view) {
  // Скрыть все
  document.querySelectorAll('[data-view-panel]').forEach(p => p.hidden = true);
  
  // Показать выбранную
  document.querySelector(`[data-view-panel="${view}"]`)?.removeAttribute('hidden');
}
```

### 2.6. Интеграция чата (ADR-011)

**Вариант A (рекомендуемый):** Кнопка «💬 История проекта» открывает modal с thread-ом (полные сообщения + интерфейс как `/chat`).

**Вариант B:** Mini-chat в боковой панели справа (нужна дополнительная вёрстка).

---

## 3. Consequences

### Плюсы

- **Owner видит что-то полезное с первого взгляда** — проекты + готовность + действия.
- **1-click actions** — нет навигации по 5 вкладкам.
- **Интеграция с workspace** — артефакты видны и открываемы (ADR-010).
- **Масштабируемо** — по мере добавления проектов список растёт, но структурирован.
- **Chat threads привязаны к проектам** — история обсуждений видна для каждого проекта (ADR-011).

### Минусы / Риски

- **Kanban перестаёт быть главной** — тимлид и лиды отделов привыкли к доске. Нужно переучить.
  - Mitigation: Kanban доступна из sidebar как `[🗂 Доска (Kanban)]`, её функциональность не меняется.
- **Производительность на 100+ проектов** — список может стать медленным.
  - Mitigation: пагинация (top 20 active projects), поиск/фильтр по `project_slug`.
- **Логика группировки по project_slug** — если project_slug не указан явно в задаче, нужно инферировать из path.
  - Mitigation: в ADR-010 уже уточнено как определяется project_slug (из path или fallback на department).
- **Double-management**: owner видит проекты, но тимлид управляет отделами. Confusion потенциальна.
  - Mitigation: clear communication что Owner Dashboard для owner-а (проекты), а тимлид использует Kanban (отделы).

---

## 4. Implementation Plan

### Phase 2.0 B2 — Backend + Data Model

| ID | Задача | Owner | Сложность | Зависит от |
|---|---|---|---|---|
| **B2.1** | Логика группировки tasks по project_slug (из path + fallback) | backend | Easy (~50 LoC) | ADR-010 |
| **B2.2** | Endpoint `GET /api/projects` (группировка, progress, action_items) | backend | Medium (~200 LoC) | B2.1, task_artifacts |
| **B2.3** | Endpoint `GET /api/projects/<slug>` (детали + chat_thread) | backend | Medium (~150 LoC) | B2.2, chat_threads (ADR-011) |
| **B2.4** | Endpoints: `POST /accept-task`, `POST /start-task`, `POST /unblock`, `POST /open-folder` | backend | Medium (~250 LoC) | B2.2, task state machine |
| **B2.5** | Smoke-тесты: создать фейковый проект → проверить группировку → action items | qa | Easy (~100 LoC) | B2.4 |

**Acceptance B2:** Backend возвращает структурированные проекты с progress + action items из `/api/projects`.

### Phase 2.0 F3 — Frontend + UI

| ID | Задача | Owner | Сложность | Зависит от |
|---|---|---|---|---|
| **F3.1** | Новый шаблон `owner-dashboard.html` (layout grid + project cards) | frontend | Medium (~300 LoC) | B2.2 |
| **F3.2** | JavaScript компонент loadProjects + renderProjectCard | frontend | Medium (~200 LoC) | F3.1 |
| **F3.3** | CSS стили: cards, progress bar, action items, responsive | frontend | Easy (~150 LoC) | F3.2 |
| **F3.4** | Sidebar: переделать nav-структуру (Dashboard главная, Kanban вторая) | frontend | Easy (~50 LoC) | F3.1 |
| **F3.5** | Event handlers: кнопки `[Принять]`, `[▶ Запустить]`, `[Разблокировать]`, `[📂 Открыть]` | frontend | Medium (~150 LoC) | B2.4 |
| **F3.6** | Modal для истории проекта (thread из чата или inline) — placeholder если ADR-011 не готов | frontend | Medium (~100 LoC) | B2.3, ADR-011 (optional) |
| **F3.7** | UX test: owner открывает главную → видит 2-3 проекта → нажимает кнопку → действие происходит | qa | Medium (~50 LoC) | F3.5 |

**Acceptance F3:** Owner открывает `/` → видит карточки с проектами, может принять/запустить задачи 1 кликом.

### Phase 2.0 F4 — Polish + Integration

| ID | Задача | Owner | Сложность |
|---|---|---|---|
| **F4.1** | Пагинация / лимит проектов на экране (top 20, остальные в архив) | frontend | Easy |
| **F4.2** | Поиск / фильтр по project_slug или title | frontend | Easy |
| **F4.3** | Кнопка «Архив» — показать завершённые проекты (collapsible) | frontend | Easy |
| **F4.4** | Интеграция с ADR-011 — button «История проекта» открывает `/chat?thread=<id>` | frontend | Medium |
| **F4.5** | Рефреш на websocket / poll (из ADR-011 realtime или простой interval) | frontend | Medium |
| **F4.6** | Стили dark/light theme (inherit from kanban.css) | frontend | Easy |
| **F4.7** | i18n: ключи dashboard (ru.json, en.json) | frontend | Easy |

---

## 5. Alternatives Considered

### 5.1. Добавить group-by-project в существующий Kanban

Вместо новой страницы, добавить toggle в текущий Kanban: `[View: By Status | By Project]`.

**Отвергнуто**, потому что:
- Старый Kanban уже перегружен (269 задач, 5 колонок).
- Группировка по проектам требует полностью другого layout (не 5 колонок).
- Owner dashboard — отдельный use case от тимлид workflow.

### 5.2. Использовать таблицу (Excel-like) вместо карточек

Таблица: столбцы project_slug, progress%, action count, files, last_update.

**Отвергнуто**, потому что:
- Карточки более читаемы и привлекательны (особенно для не-техничного owner-а).
- Кнопки (action items) с карточками выглядят естественнее.
- Таблица хороша для аналитики, но тут нужна actionability.

### 5.3. Объединить Owner Dashboard и Chat на одной странице (50/50 сплит)

Слева dashboard, справа chat thread.

**Отвергнуто**, потому что:
- ADR-011 уже спроектировал `/chat` как полноценную страницу с собственным layout (левая колонка threads, центр message, правая panel).
- Merging нарушит дизайн обеих.
- Лучше интеграция через модальные окна (сейчас рекомендуемый подход).

---

## 6. Resolved Decisions

1. **Главная `/` переезжает на Owner Dashboard** — Kanban остаётся как `/board` (или вторая вкладка в sidebar).
2. **project_slug инферируется из workspace path** — при необходимости явное поле в tasks добавится в v2.1 (см. ADR-010 §2.6).
3. **Sidebar: Dashboard главная** — активная по умолчанию, Kanban вторая.
4. **Chat история привязана к проекту** — modal или новая вкладка (`/chat?project=<slug>`), но **не inline** в карточку (иначе громоздко).
5. **Action items: ограничение на экране** — если item'ов >10, collapse + `[+ Показать все]` button.

---

## 7. Related ADRs

- **ADR-010** — workspace + task_artifacts (source данных для артефактов).
- **ADR-011** — chat threads (интеграция истории проектов).
- **ADR-009** — managing-director (owner общается через Управляющего).
- **ADR-003** — departments (логика отделов для action items `assignee`).

---

## 8. References

- Owner-vision сессия 2026-05-25: «куда смотреть, где результат».
- Task `#02215A903F04` — Owner Dashboard redesign.
- Phase 2.0 эпик — client artifacts, workspace management.
- Current main page: `dashboard/templates/kanban.html` (~150 строк).
- Current API: `dashboard/app.py` (Flask endpoints).

---

## Changelog

- **2026-05-25:** Initial Proposed draft.
  - Спроектирован layout Owner Dashboard (grid card'ов по проектам).
  - Описаны endpoint'ы для группировки, progress, action items.
  - Интеграция с workspace (ADR-010) и chat (ADR-011).
  - Implementation plan на Phase 2.0 B2 (backend) + F3 (frontend).

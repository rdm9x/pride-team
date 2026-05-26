# ADR-010 — Workspace + task_artifacts архитектура

- **Status:** Proposed (2026-05-25)
- **Date:** 2026-05-25
- **Authors:** Claude-сессия (Haiku 4.5) совместно с архитектором
- **Epic:** Phase 2.0 — Client artifacts storage (parent task `45d24740bc79`)
- **Supersedes:** —
- **Depends on:**
  - **ADR-003** (`0003-departments.md`) — модель `departments`.
  - **ADR-005** (`0005-inter-department.md`) — cross-department задачи.
- **Related:**
  - **B1 (Phase 2.0 SQL+MCP)** — реализация `register_task_artifact` MCP-tool и REST endpoints (зависит от этой ADR).

---

## 1. Context

### 1.1. Проблема: артефакты создаются в случайных местах

Роли devboard (тимлид, бэкенд, маркетолог, юрист, дизайнер) генерируют **client-facing артефакты** — лендинги, техническую документацию, отчёты, копирайт, графику и т.д. Сейчас эти файлы:

- Создаются в разных местах (tmp/, workspace/, docs/, случайные папки в /tmp OS-a).
- Не привязаны к задачам — owner не знает, где найти результат.
- Не отслеживаются в БД — нет истории, нет метаданных.
- Не видны в UI — карточка задачи не показывает что-то вроде «📎 3 файла» с кнопками открытия.
- Теряются при очистке временных папок.

### 1.2. Требование от owner'а (Phase 2.0 фаза)

Owner сказал (2026-05-25): **«Нужна единая папка для всех артефактов по проекту, структурированно по задачам. Быстро найти любой файл — одна кнопка в UI»**.

Проект здесь интерпретируется как **project-slug** (например `landing-outdoor-2026`, `marketing-site-v2`). В контексте v2.0 с отделами, проект часто охватывает задачи из **нескольких отделов** (маркетинг + разработка + юристы на один лендинг).

### 1.3. Текущее состояние `.gitignore`

В `.gitignore` уже зарезервирована структура:

```
/workspace/**/*          # игнорируем все содержимое
!/workspace/
!/workspace/.gitkeep     # но保храним сами папки
!/workspace/dev/
!/workspace/marketing/
!/workspace/demo-project/
!/workspace/demo-project/landing.html  # пример E2E теста
```

Это подтверждает что решение **локально хранить артефакты в корне репо** — уже намеченно архитектором. Задача ADR — формализовать это + добавить БД-слой + MCP/REST API.

## 2. Decision

### 2.1. Структура workspace

Все артефакты хранятся в **`workspace/<project-slug>/<task-id>/<filename>`** в корне репо:

```
workspace/
  landing-outdoor-2026/
    a1b2c3d4e5f6/          # task-id (12 hex, uuid-формат)
      landing.html
      style.css
      robots.txt
    a1b2c3d4e5f7/
      seo-report.pdf
      keywords.json
  marketing-site-v2/
    c5d6e7f8a9b0/
      copytext.md
      og-image.png
```

**project-slug** (**не** department-id):

- Вводится в момент создания первой задачи с артефактами (либо явно указывается в frontmatter задачи, либо наследуется из контекста).
- Формат: `^[a-z][a-z0-9-]{1,63}$` (как `department-id`).
- Цель: группировать артефакты по логическим проектам, которые могут охватывать несколько отделов.
- **Опционально** в v1.0 — если проект не указан, используется `default-project` либо `department-slug`.

### 2.2. Таблица `task_artifacts` (уже в БД!)

```sql
CREATE TABLE task_artifacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT NOT NULL,
  file_path TEXT NOT NULL,                 -- относительный путь внутри workspace/
  kind TEXT NOT NULL,                      -- 'file' | 'folder'
  created_at INTEGER NOT NULL,             -- Unix epoch seconds
  FOREIGN KEY (task_id) REFERENCES tasks(id),
  CONSTRAINT unique_artifact UNIQUE (task_id, file_path)
);

CREATE INDEX idx_artifacts_task ON task_artifacts(task_id);
CREATE INDEX idx_artifacts_created ON task_artifacts(created_at);
```

**Поля:**

- **`id`** — первичный ключ (autoincrement).
- **`task_id`** — внешний ключ на `tasks.id`. Один артефакт принадлежит одной задаче.
- **`file_path`** — **относительный путь** вида `workspace/project-slug/task-id/filename` или просто `filename` (зависит от реализации — см. §4.1).
- **`kind`** — тип: `'file'` или `'folder'` (зарезервировано для будущего, где папка может содержать несколько файлов).
- **`created_at`** — timestamp создания/регистрации артефакта.
- **Уникальность** — пара `(task_id, file_path)` не может повторяться (одна файловая ссылка на задачу).

### 2.3. MCP-инструмент `register_task_artifact`

Новый MCP-tool в `mcp_server/` (реализуется в B1):

```python
def register_task_artifact(
    task_id: str,
    file_path: str,
    kind: str = 'file'
) -> dict:
    """Зарегистрировать артефакт в БД и связать его с задачей.
    
    Args:
        task_id: ID задачи (12 hex символов, uuid).
        file_path: Относительный путь файла внутри workspace/.
                   Пример: 'workspace/landing-outdoor-2026/a1b2c3d4e5f6/landing.html'
                   или просто 'landing.html' (path будет нормализован).
        kind: 'file' (по умолчанию) или 'folder'.
    
    Returns:
        {
            'status': 'ok' | 'file_not_found' | 'invalid_task_id' | 'db_error',
            'artifact_id': <int> | None,
            'task_id': task_id,
            'file_path': нормализованный file_path,
            'kind': kind,
            'created_at': Unix timestamp
        }
    
    Side effects:
        - Вставляет строку в task_artifacts.
        - На диске проверяет что файл существует (если kind='file').
        - На диске НЕ создаёт папки автоматически (пусть роль или клиент сначала создадут).
    """
```

**Контракт:**

- **Валидация**: `task_id` должен существовать в `tasks`. `file_path` должен существовать на диске.
- **Нормализация**: `file_path` нормализуется в вид `workspace/project-slug/task-id/filename` (если не полный путь).
- **Идемпотентность**: повторный вызов с одной и той же `(task_id, file_path)` → 409 Conflict или просто возвращает существующий `artifact_id` (зависит от решения B1, документируется в коде).
- **Ошибки**: отсутствие файла, невалидный task_id, ошибка БД — детально в `status`.

### 2.4. REST API endpoints

Реализуются в `dashboard/` (backend Flask/FastAPI, в B1):

#### 2.4.1. `GET /api/tasks/<task_id>/artifacts`

Получить список артефактов задачи.

**Запрос:**

```
GET /api/tasks/a1b2c3d4e5f6/artifacts
```

**Ответ (200 OK):**

```json
{
  "status": "ok",
  "task_id": "a1b2c3d4e5f6",
  "artifacts": [
    {
      "id": 42,
      "file_path": "workspace/landing-outdoor-2026/a1b2c3d4e5f6/landing.html",
      "kind": "file",
      "created_at": 1716669600,
      "size_bytes": 15234,
      "mime_type": "text/html"
    },
    {
      "id": 43,
      "file_path": "workspace/landing-outdoor-2026/a1b2c3d4e5f6/style.css",
      "kind": "file",
      "created_at": 1716669610,
      "size_bytes": 3421,
      "mime_type": "text/css"
    }
  ]
}
```

**Ошибки:**

- `404` — task_id не найден.
- `500` — ошибка БД.

#### 2.4.2. `POST /api/open-file`

Открыть файл локально (на машине пользователя). **Это специальный endpoint для dev-режима.**

**Запрос:**

```json
POST /api/open-file
{
  "file_path": "workspace/landing-outdoor-2026/a1b2c3d4e5f6/landing.html"
}
```

**Ответ (200 OK):**

```json
{
  "status": "opened",
  "file_path": "workspace/landing-outdoor-2026/a1b2c3d4e5f6/landing.html",
  "absolute_path": "/Users/dm_pc/Desktop/pride-team-v1.0/workspace/landing-outdoor-2026/a1b2c3d4e5f6/landing.html",
  "message": "Opening in default app..."
}
```

**Реализация:**

- На Python: `subprocess.Popen(['open', absolute_path])` (macOS), `subprocess.Popen(['xdg-open', absolute_path])` (Linux), `os.startfile(absolute_path)` (Windows).
- **Безопасность**: валидировать что `file_path` находится внутри `workspace/` (path traversal prevention).

#### 2.4.3. `POST /api/tasks/<task_id>/artifacts` (опционально)

Загрузить файл через веб-интерфейс (multipart/form-data). **Для будущего (не в Phase 2.0 B1).**

```
POST /api/tasks/a1b2c3d4e5f6/artifacts?project_slug=landing-outdoor-2026
Content-Type: multipart/form-data

file: <binary data>
```

Ответ: `artifact_id`, `file_path`, и т.д. (как `register_task_artifact`).

### 2.5. UI: карточка задачи

В дашборде (Phase 3), карточка задачи показывает:

```
┌─ Task a1b2c3d4e5f6 ────────────────────────┐
│ Title: Лендинг для рекламных конструкций   │
│ Status: in_progress                         │
│ ...                                         │
│                                             │
│ 📎 Артефакты (3 файла)                     │
│ ├─ [📄 landing.html]    [↓] [🔗]            │
│ ├─ [🎨 style.css]       [↓] [🔗]            │
│ └─ [📊 seo-report.pdf]  [↓] [🔗]            │
│                                             │
│ Кнопки: [Скачать]  [Открыть папку]  [+]    │
└─────────────────────────────────────────────┘
```

**Иконки:**

- `📄` — текстовый файл (`.html`, `.txt`, `.md`, `.json`).
- `🎨` — изображение (`.png`, `.jpg`, `.svg`).
- `📊` — документ (`.pdf`, `.docx`).
- `🎬` — видео (`.mp4`, `.webm`).
- `📁` — папка (если `kind='folder'`).

**Кнопки:**

- `[↓]` — скачать файл (GET `/api/download-file` + Content-Disposition).
- `[🔗]` — открыть локально (`POST /api/open-file`).
- `[+]` — добавить новый артефакт (в будущем, upload endpoint).

Если артефактов нет, показать:

```
💬 Нет артефактов. Роли могут добавлять файлы через MCP.
```

### 2.6. project_slug: как он определяется

**В Phase 2.0:**

1. Если задача **создана явно с `project_slug` в frontmatter** → используется это значение.
2. Если задача **кросс-departmental** (см. ADR-005) → может быть наследован от parent-задачи либо из контекста owner'а.
3. Если **ничего не указано** → используется `department_id` задачи как fallback (e.g., `marketing`, `dev`).

**В будущем (v2.1):**

- Явное поле `project_slug` в таблице `tasks` (зарезервировано для v2.1 миграции).
- UI для owner'а: при создании многоотдельной задачи выбрать/назвать проект.

### 2.7. Очистка workspace при удалении

**Мягкое удаление** (логичное, как остальное в devboard):

- При `DELETE /api/tasks/<task_id>` — задача мягко удаляется (soft-delete, `deleted_at` или статус → `archived`).
- Артефакты в БД **НЕ удаляются** (остаются для истории/восстановления).
- Файлы на диске **сохраняются** (owner может скачать).

**Жёсткое удаление** (опционально, вручную):

- Admin-команда `devboard cleanup-workspace --days 30` → удаляет файлы старше 30 дней из `workspace/`.
- Перед удалением на диске — проверка что запись есть в БД (не трогаем случайные файлы).

## 3. Consequences

### Плюсы

- **Централизованное хранилище**: все артефакты в одном месте, структурированны по project-slug и task-id.
- **Быстрый поиск**: owner видит файлы прямо в карточке задачи (10 символов task-id → click → артефакты).
- **Версионирование по БД**: таблица `task_artifacts` отслеживает когда файл был создан, можно логировать изменения.
- **Интеграция с MCP**: роли могут регистрировать артефакты не покидая Python-контекста `register_task_artifact` → 1 функция вместо ручного file_copy.
- **Масштабируемость**: если в будущем перейти на S3 — просто изменить path_resolution + storage backend. Контракт (таблица + API) не меняется.
- **Безопасность**: path traversal protected за счёт валидации в `register_task_artifact`.

### Минусы / Риски

- **Репо растёт в размере**: workspace-папки не игнорируются git'ом в целом, только их содержимое. Если рассчитывать на очень частые артефакты (megabyte-scale daily), репо может раздуться. Решение: жёсткая ротация, S3 backup, лимит размера.
- **Concurrency на диске**: если две роли одновременно пишут в одну workspace-папку (race condition). Решение: документировать в `register_task_artifact` что функция atomic и thread-safe за счёт БД (UNIQUE constraint).
- **Path нормализация**: на разных ОС (Windows vs Unix) path-сепараторы отличаются (`\` vs `/`). Решение: в коде всегда использовать `/`, нормализовать на входе в `register_task_artifact`.
- **Cleanup logic**: если workspace вырос в 1GB+, удаление может быть медленным. Решение: background job (cron или task в очереди), не блокирует API.
- **Отсутствие квот**: owner может нечаянно заполнить диск. Решение: warning при приближении к лимиту (e.g., `if workspace_size > 5GB: log(warning)`), документировать в `AGENTS.md`.

## 4. Alternatives Considered

### 4.1. Хранить артефакты в облаке (S3 / Google Drive / Dropbox)

**Отвергнуто**, потому что:

- Требует API-ключей, дополнительные зависимости (boto3, google-auth), усложняет dev-workflow.
- Сетевая задержка при открытии файла (vs локальное `open`).
- Непредсказуемый downtime облачного сервиса.
- **v2.0 ориентирована на self-hosted** (дашборд на localhost, БД локально).

**Fallback на будущее (v2.1+):** если потребуется shared workspace между несколькими машинами, переносим в S3 за отдельной ADR. На уровне кода — просто заменяем path-resolution в `register_task_artifact`, контракт не меняется.

### 4.2. Хранить артефакты в git (без gitignore)

**Отвергнуто**, потому что:

- Git не оптимизирован для бинарных файлов (`.pdf`, `.png`).
- История git раздевается на каждый коммит артефакта (репо медленнее).
- Нарушает принцип separations concerns: product-code и client-artifacts смешиваются.
- Сложнее исключить чувствительные данные (если в артефактах окажутся credentials).

### 4.3. Хранить в папке `docs/`

**Отвергнуто**, потому что:

- `docs/` в git'е (не gitignored) → проблема 4.2 повторяется.
- Смешивает архитектурную документацию (`.md`, `.svg` диаграммы, ADR) с client-artifacts (лендинги, отчёты, копирайт).
- Сложнее отличить что скоммитить, что нет.

### 4.4. Каждая задача создаёт свой временный процесс + `tmpdir`

**Отвергнуто** (текущий anti-pattern), потому что:

- Файлы теряются при перезагрузке machine / очистке `/tmp`.
- Owner не может найти результат (случайное имя на /tmp).
- Нет истории (каждый запуск — новая папка).
- Невозможно link артефакты в UI (нет ID в БД).

## 5. Implementation Plan

Реализация разбита на фазы:

### Phase 2.0 B1: Core infrastructure

| ID | Что | Owner | Зависит от |
|---|---|---|---|
| **B1.1** | Этот ADR (Proposed) | архитектор | — |
| **B1.2** | Миграция БД: добавить `project_slug` в `tasks` (опционально v2.1) | backend | B1.1 |
| **B1.3** | MCP-tool `register_task_artifact` + валидация + atomicity | backend | B1.1 |
| **B1.4** | REST endpoints: `GET /api/tasks/<id>/artifacts`, `POST /api/open-file` | backend | B1.3 |
| **B1.5** | Smoke-тесты: создать фейковую задачу → регистрировать файл → проверить API | qa | B1.4 |

### Phase 3: UI + Polish (2.1 и позже)

| ID | Что | Owner | Зависит от |
|---|---|---|---|
| **P3.1** | Карточка задачи: компонента «Артефакты» (список + иконки + кнопки) | frontend | B1.4 |
| **P3.2** | Download endpoint: `GET /api/download-file?path=...` (Content-Disposition) | backend | B1.4 |
| **P3.3** | Upload endpoint: `POST /api/tasks/<id>/artifacts` (multipart) | backend | B1.4 |
| **P3.4** | Cleanup: background job `workspace-gc` + лимит размера | devops | B1.3 |

Контракт (таблица + MCP + REST) **стабилен** после B1.4 и не меняется без новой ADR.

## 6. Resolved Decisions

**Вопрос: project_slug как часть Primary Key?**

Ответ (2026-05-25): Нет. Primary Key остаётся `task_id` (через FK на `tasks.id`). `project_slug` — метаданные, хранятся либо в отдельном поле `tasks.project_slug` (v2.1), либо конструируются из path (v2.0). Это упрощает миграцию и позволяет задаче менять проект без переноса артефактов.

**Вопрос: Поддержка папок (kind='folder')?**

Ответ (2026-05-25): Зарезервировано в схеме для будущего. В v2.0 регистрируются только файлы (`kind='file'`). Если понадобится регистрировать папки как целое (не отдельные файлы внутри) — простое расширение, breaking change не требуется.

## 7. References

- Task artifact requirement: `45d24740bc79` (A1 Phase 2.0).
- Workspace structure: `.gitignore`, линии 200-214.
- DB schema: `mcp_server/devboard_tasks/db.py`, линии 129-140 (таблица `task_artifacts`).
- Phase 2.0 эпик: cross-department workflow (ADR-005), departments (ADR-003).
- Related MCP-tool (B1.3): `register_task_artifact(task_id, file_path, kind)` (в разработке).

## Changelog

- **2026-05-25:** Initial Proposed draft (Claude Haiku 4.5, сессия task `45d24740bc79`).
  - Сформализовано решение по workspace-структуре, task_artifacts таблице, MCP/REST API контрактам.
  - Отвергнуты альтернативы: облако, git, docs-папка, tmpdir-antipattern.
  - Зарезервированы поле `project_slug` и kind='folder' для v2.1.

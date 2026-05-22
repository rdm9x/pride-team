---
тип: карта_репозитория_для_агентов
проект: devboard
читать_первым: да
обновлено: 2026-05-22
версия: v1.6
---

# AGENTS.md — карта репозитория Devboard

> Если ты — Claude-агент (тимлид, бэкенд, qa, архитектор, frontend, devops, техписатель)
> которому делегировали работу, **прочитай этот файл первым**.
> Не делай `ls` для разведки — структура и точки входа описаны ниже.

---

## TL;DR что где живёт

| Папка | Что |
|---|---|
| `dashboard/` | Flask UI + REST API (port 4999) |
| `mcp_server/` | MCP-сервер `pride-tasks` (используется ролями через MCP) |
| `roles/` | System-prompts ролей (markdown с frontmatter) |
| `commands/` | bash/ps1 скрипты запуска (`devboard-start.sh`, `-stop`, `-work`, `-test`) |
| `data/` | SQLite БД, бекапы, .env.local, team.log |
| `docs/` | ADR / qa-отчёты / launch-материалы / security audit |
| `tests/` | top-level pytest (есть также `dashboard/tests/`, `mcp_server/tests/`) |
| `scripts/` | `stress_test.py` — нагрузочный тест MCP-сервера; `migrate_*.py` — DB-миграции |
| `llm/` | заготовки для multi-LLM provider (Claude/OpenAI/Ollama, см. ADR-001) |

Корневые .md (`README*.md`, `ARCHITECTURE.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `DEPLOYMENT.md`) — для конечных пользователей и контрибьюторов. **Не плодить новые .md в корне** без согласования.

---

## dashboard/ — UI и REST API

```
dashboard/
├── app.py                 ~1750 строк, главный Flask. Все REST endpoints, SSE для live-чата,
│                          парсер stream-json от тимлид-сессии, safety-net.
├── pyproject.toml         deps дашборда (Flask, werkzeug, …)
├── .venv/                 ← venv создаёт setup.py / devboard-start.sh
├── static/
│   ├── app.js             ~1900 строк, ВСЯ frontend-логика SPA.
│   ├── style.css          ~1700 строк, Liquid Glass design (light + dark)
│   ├── i18n/
│   │   ├── ru.json        Русские строки (включает: settings.*, wizard.*, tour.step.*,
│   │   │                  stats.*, task.tldr_label/questions_label/acceptance_label,
│   │   │                  notifications.*, roles.col.*)
│   │   └── en.json        Английские строки (те же ключи, синхронно)
│   └── js/
│       ├── i18n.js        i18n-loader: window.t(), setLocale(), applyI18nToDOM()
│       ├── locale-switcher.js  UI-переключатель языка интерфейса (S2.1)
│       └── tour.js        Onboarding-тур (12 шагов, S5.4)
├── templates/
│   └── kanban.html        ЕДИНСТВЕННЫЙ шаблон (SPA). Все views = `<section data-view>`.
│                          Включает first-run wizard (модальный оверлей, #first-run-wizard).
└── tests/
    └── test_*.py          ~116 тестов, pytest
```

### REST endpoints (живут в app.py)
| Endpoint | Method(s) | Описание |
|---|---|---|
| `/api/tasks` | GET, POST | CRUD задач (список, создание) |
| `/api/tasks/<id>` | GET, PATCH, DELETE | Чтение / обновление / удаление задачи |
| `/api/tasks/<id>/parsed` | GET | Parsed view (TL;DR + questions + acceptance), reader-mode (S5.5/S6.2) |
| `/api/tasks/<id>/{comment,approve,reject}` | POST | Действия над задачей |
| `/api/tasks/<id>/dependencies` | POST, DELETE `…/<blocker_id>` | Управление зависимостями |
| `/api/inbox` | GET | Inbox (approvals / reviews / questions) |
| `/api/chat` | GET, POST | Чат-сообщения |
| `/api/team/{start,stop,status}` | POST/GET | Управление тимлид-сессией |
| `/api/team/auto` | POST | Включить/выключить auto-mode тимлида (S3.6) |
| `/api/team/stream` | GET (SSE) | Server-Sent Events: live-поток сессии |
| `/api/team/silence` | GET | Проверка молчания тимлида (было ли активности) |
| `/api/router/pick` | GET | Какую модель выбирает роутер для следующей сессии |
| `/api/usage` | GET | Сырая статистика использования |
| `/api/stats/aggregates` | GET | Агрегаты по задачам (по статусам, ролям, приоритетам; кешируется по диапазону дат) (S3.2) |
| `/api/settings/static-info` | GET | Read-only constants: доступные модели, auto-лимиты, путь к backups (S2.1) |
| `/api/roles` | GET, POST | Список ролей / создание |
| `/api/roles/<name>` | PUT, DELETE | Обновление / удаление роли |
| `/api/roles/import` | POST | Импорт роли из файла |
| `/api/demo` | POST, DELETE | Создать / удалить демо-данные (идемпотентен) (S3.6) |
| `/api/open-folder` | POST | Открыть папку в системном файловом менеджере (Finder / Explorer / xdg-open) |
| `/healthz` | GET | Health probe |

### SPA views (`data-view="..."`)

| View | Описание |
|---|---|
| `board` | Kanban-доска (default) |
| `inbox` | Approvals / reviews / questions |
| `stats` | Статистика по задачам, графики (S3.2) |
| `roles` | CRUD ролей |
| `archive` | Архив завершённых задач |
| `settings` | Настройки: locale, expertise, модели, бекапы, сброс онбординга (S2.1+) |

First-run wizard — модальный оверлей `#first-run-wizard` (4 шага, прогресс-бар), показывается один раз при `!localStorage.first_run_done`.

### Где править что
| Задача | Куда смотреть |
|---|---|
| Новый endpoint | `dashboard/app.py` после блока существующих `@app.<verb>` |
| Новая view в SPA | `templates/kanban.html` (`<section data-view="…">`) + `static/app.js` (`switchView`, `load*`) |
| Новый i18n-ключ | `static/i18n/{ru,en}.json` (синхронно в обоих) |
| Стили | `static/style.css`, секции прокомментированы (`/* ============ */`) |
| Эмодзи автора | `static/app.js` `AUTHOR_EMOJI` мап |

---

## mcp_server/ — MCP-сервер pride-tasks

```
mcp_server/
├── pyproject.toml          deps MCP-сервера (mcp, dotenv, httpx)
├── .venv/                  ← создаётся через uv в setup.py
└── pride_tasks/
    ├── __init__.py
    ├── __main__.py         entry point `python -m pride_tasks`
    ├── server.py           FastMCP setup + регистрация tools
    ├── tools.py            ~700 строк, 11 MCP-функций
    ├── db.py               SQLite + fcntl/msvcrt lock + миграции
    ├── models.py           константы ROLES, STATUSES, PRIORITIES
    ├── router.py           алгоритмический выбор модели (haiku/sonnet/opus)
    └── alerts.py           Telegram-нотификации
└── tests/                  ~118 тестов
```

### 14 MCP-tools (имена в Claude после префикса `mcp__pride-tasks__`)
- `list_tasks`, `get_task`, `create_task`, `update_task`, `claim_task`
- `add_comment`, `submit_result`
- `list_roles`
- `chat_recent`, `chat_post`, `notify_user`
- `add_dependency`, `remove_dependency`, `get_dependencies`

### Где править что
| Задача | Куда |
|---|---|
| Новый MCP-tool | `tools.py` + регистрация в `server.py` |
| Изменить роутер моделей | `router.py` (`pick`, `pick_from_db`) + тесты `tests/test_router.py` |
| Изменить схему БД | `db.py` (`init_db`) + миграция `scripts/migrate_*.py` |

---

## roles/ — system-prompts

```
roles/
├── тимлид.md           Координатор; декомпозиция, делегирование, ревью.
├── бэкенд.md           Python, Flask, MCP, SQLite.
├── qa.md               Тесты, smoke, регресс.
├── архитектор.md       ADR, абстракции, дизайн.
├── frontend.md         HTML/CSS/JS, i18n, UX.
├── devops.md           Docker, GitHub Actions, deploy, security.
├── техписатель.md      English docs, README, ARCHITECTURE.
├── examples/           5 шаблонов ролей-примеров для marketplace.
│   ├── code-reviewer.md, data-analyst.md, designer.md,
│   ├── echo.md, pm.md, security-auditor.md
└── validator.py        E7.4 — валидатор формата ролей (pydantic + размер).
```

Frontmatter обязательные поля (см. ADR-002 `docs/adr/0002-role-format.md`):
`тип`, `роль`, `проект`, `name`, `name_en` (с S2.3), `description_короткое`, `schema_version`.

---

## commands/ — скрипты запуска

| Файл | Что |
|---|---|
| `devboard-start.sh` / `.ps1` | Поднимает Flask-дашборд на :4999 |
| `devboard-stop.sh` / `.ps1` | Глушит дашборд (по `data/dashboard.pid`) |
| `devboard-work.sh` / `.ps1` | Запускает claude-сессию тимлида с MCP. Использует `router.py model-only` |
| `devboard-test.sh` / `.ps1` | Прогон всех pytest |

---

## data/ — runtime state (gitignored)

```
data/
├── tasks.db                SQLite БД канбана
├── tasks.db-{shm,wal,lock} WAL-файлы
├── tasks.db.lock           fcntl/msvcrt-lock для atomic writes
├── .env.local              TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (chmod 600)
├── .output_locale          язык вывода ролей (ru/en, S2.2)
├── .user_expertise         уровень пользователя (tech/non-tech, S3.4)
├── .gitkeep                маркер чтобы папка data/ трекалась git (S5)
├── team.log                сырой stream-json от claude (для дебага)
├── dashboard.log           stdout/stderr Flask
├── team.pid                PID активной сессии тимлида (если есть)
├── dashboard.pid           PID Flask
└── backups/                автобекапы БД (каждый час, 7 дней)
```

---

## LocalStorage keys (browser)

These keys are written by `static/app.js`. Useful when debugging front-end state or writing tests that need a known browser environment.

| Key | Values | Set by |
|---|---|---|
| `ui_locale` | `"ru"` / `"en"` | locale-switcher.js (S2.1) |
| `output_locale` | `"ru"` / `"en"` | Settings view (S2.2); mirrors `data/.output_locale` |
| `theme` | `"light"` / `"dark"` | Theme toggle button |
| `user_expertise` | `"tech"` / `"non-tech"` | Settings view (S3.4); mirrors `data/.user_expertise` |
| `notifications.enabled` | `"true"` / `"false"` | Notifications settings (S6.6) |
| `notifications.level` | `"all"` / `"important"` / `"none"` | Notifications settings (S6.6) |
| `first_run_done` | `"1"` | Set after first-run wizard completes |
| `last_view` | e.g. `"board"`, `"stats"` | Persists active view across reloads |
| `acceptance_<task_id>` | JSON `{[item]: bool}` | Acceptance checklist state per task (S6.2) |

---

## docs/ — артефакты процесса

```
docs/
├── adr/                    Architecture Decision Records
│   ├── 0001-llm-provider.md
│   ├── 0002-role-format.md
│   ├── 0003-departments.md       v2.0 design — модель Department (NOT YET IMPLEMENTED)
│   ├── 0004-hr-role.md           v2.0 design — HR pipeline (NOT YET IMPLEMENTED)
│   └── 0005-inter-department.md  v2.0 design — cross-task правила (NOT YET IMPLEMENTED)
├── launch/                 Маркетинг-драфты (Twitter / dev.to / Show HN / video)
├── qa/                     QA-отчёты (coverage, i18n, perf)
├── security-audit/         gitleaks отчёты
├── screenshots/            Иллюстрации для README
└── i18n-audit.md           Аудит локализации
```

---

## tests/ — где какие

```
tests/                      top-level smoke
dashboard/tests/            ~116 тестов на Flask + REST + safety-net
mcp_server/tests/           ~118 тестов на MCP-tools, db, router
smoke/tests/                hello-world смоук
```

Прогон всех:
```bash
bash commands/devboard-test.sh
```

---

## Частые подводные камни

1. **Кириллица в путях** — раньше папки назывались `дашборд/`, `роли/`, `команды/`, `mcp_сервер/`. **Переименовано в S1.1** в `dashboard/`, `roles/`, `commands/`, `mcp_server/`. Импорт `pride_tasks` через `sys.path.insert` в `dashboard/app.py:26-28` (там объяснение почему).
2. **Изменения в `app.py`** — нужен **перезапуск дашборда** (Python код кеширован в процессе). `bash commands/devboard-stop.sh && bash commands/devboard-start.sh`.
3. **Изменения статики** (`static/*.js`, `*.css`, templates) — НЕ требуют перезапуска, Flask отдаёт с `Cache-Control: no-store`.
4. **Subagent через Task tool не имеет MCP**. После Task tool **тимлид сам** делает `update_task` для всех подзадач.
5. **БД в `.gitignore`** — `data/tasks.db` не уезжает на GitHub. Новый пользователь получает чистую БД через `setup.py`.
6. **На macOS порт 5000 занят AirPlay Receiver** → используем **4999**.
7. **Settings tab** (v1.2) — читает `/api/settings/static-info` (GET): возвращает список доступных моделей, автолимиты, путь к backups. Сюда же сохраняется `output_locale` и `user_expertise` (POST `/api/settings`).
8. **Statistics tab** (v1.3) — читает `/api/stats/aggregates` (GET): агрегаты по задачам (по статусам, ролям, приоритетам). Ответ кешируется сервером по диапазону дат.
9. **i18n** (v1.2) — строки в `dashboard/static/i18n/{ru,en}.json`. Загружает и применяет `dashboard/static/js/i18n.js` (API: `window.t(key)`, `setLocale(lang)`, `applyI18nToDOM()`). При добавлении нового ключа — синхронно в оба файла.
10. **Plain-language mode** (v1.3) — управляется через Settings (`user_expertise: non-tech`), сохраняется в `data/.user_expertise`. `devboard-work.sh` передаёт значение тимлид-роли, которая переключается на упрощённые объяснения для нетехнического пользователя.
11. **Windows: UTF-8 required.** Without explicit encoding setup, Russian text becomes mojibake in the terminal and logs. `commands/devboard-work.ps1` sets three things at the top: `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8`, `$OutputEncoding = [System.Text.Encoding]::UTF8`, and `$env:PYTHONIOENCODING = "utf-8"`. The `subprocess.Popen` call in `app.py` that spawns the teamlead session also injects `PYTHONIOENCODING=utf-8` into the child process env. If you add any new subprocess calls on Windows, follow the same pattern.
12. **Тимлид не может поставить `done` напрямую.** Safety-net в `mcp_server/pride_tasks/tools.py` (`_safety_net_done`) перехватывает MCP-вызовы `update_task` и `submit_result` с `status=done` и форсирует `status=review` вместо этого, добавляя системный комментарий и чат-сообщение. Обойти можно только через `_bypass_safety_net=True` — это флаг для Flask UI, не для агентов. Поведение введено в S6.4 и является намеренным.
13. **v2.0 (Departments, HR) не реализовано.** ADR 0003-0005 в `docs/adr/` — это design-документы, код под них ещё не написан. Не реализовывать без явного задания.

---

## Что НЕ нужно делать

- НЕ создавать новые .md в корне без обсуждения (там и так много).
- НЕ менять структуру dashboard/static без согласования с frontend (там SPA single-file pattern).
- НЕ амендить чужие коммиты — всегда новый коммит.
- НЕ убирать `data/` из `.gitignore`.
- НЕ перезаписывать всю `data/tasks.db` — это runtime state, ломаешь существующую работу пользователя.

---

**Этот файл — живой**. При добавлении новой папки / переименовании / новой ключевой фичи — обнови AGENTS.md в том же коммите.

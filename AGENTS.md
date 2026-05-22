---
тип: карта_репозитория_для_агентов
проект: devboard
читать_первым: да
обновлено: 2026-05-22
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
| `scripts/` | миграции (`migrate_*.py`) |
| `llm/` | заготовки для multi-LLM provider (Claude/OpenAI/Ollama, см. ADR-001) |

Корневые .md (`README*.md`, `ARCHITECTURE.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `DEPLOYMENT.md`) — для конечных пользователей и контрибьюторов. **Не плодить новые .md в корне** без согласования.

---

## dashboard/ — UI и REST API

```
dashboard/
├── app.py                 ~1500 строк, главный Flask. Все REST endpoints, SSE для live-чата,
│                          парсер stream-json от тимлид-сессии, safety-net.
├── pyproject.toml         deps дашборда (Flask, werkzeug, …)
├── .venv/                 ← venv создаёт setup.py / devboard-start.sh
├── static/
│   ├── app.js             ~1900 строк, ВСЯ frontend-логика SPA.
│   ├── style.css          ~1700 строк, Liquid Glass design (light + dark)
│   ├── i18n/
│   │   ├── ru.json        Русские строки
│   │   └── en.json        Английские строки
│   └── js/
│       ├── i18n.js        i18n-loader: window.t(), setLocale(), applyI18nToDOM()
│       ├── locale-switcher.js  UI-переключатель языка интерфейса
│       └── tour.js        Onboarding-тур
├── templates/
│   └── kanban.html        ЕДИНСТВЕННЫЙ шаблон (SPA). Все views = `<section data-view>`
└── tests/
    └── test_*.py          ~116 тестов, pytest
```

### REST endpoints (живут в app.py)
| Префикс | Описание |
|---|---|
| `/api/tasks` | CRUD задач (GET список, POST create, PATCH update, DELETE) |
| `/api/tasks/<id>/{comment,approve,reject,dependencies}` | Действия над задачей |
| `/api/inbox` | Inbox (approvals / reviews / questions) |
| `/api/chat` | Чат-сообщения |
| `/api/team/{start,stop,status,silence}` | Управление тимлид-сессией |
| `/api/router/pick` | Какую модель выбирает роутер для следующей сессии |
| `/api/usage`, `/api/stats/aggregates` | Статистика |
| `/api/settings/static-info` | Read-only constants (auto-лимиты, путь к backups) |
| `/api/roles` | CRUD ролей |
| `/healthz` | health probe |

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
├── .env.local              TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (chmod 600)
├── .output_locale          язык вывода ролей (ru/en, S2.2)
├── .user_expertise         уровень пользователя (tech/non-tech, S3.4)
├── team.log                сырой stream-json от claude (для дебага)
├── dashboard.log           stdout/stderr Flask
├── team.pid                PID активной сессии тимлида (если есть)
├── dashboard.pid           PID Flask
└── backups/                автобекапы БД (каждый час, 7 дней)
```

---

## docs/ — артефакты процесса

```
docs/
├── adr/                    Architecture Decision Records
│   ├── 0001-llm-provider.md
│   ├── 0002-role-format.md
│   ├── 0003-departments.md       v2.0 — модель Department
│   ├── 0004-hr-role.md           v2.0 — HR pipeline
│   └── 0005-inter-department.md  v2.0 — cross-task правила
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

---

## Что НЕ нужно делать

- НЕ создавать новые .md в корне без обсуждения (там и так много).
- НЕ менять структуру dashboard/static без согласования с frontend (там SPA single-file pattern).
- НЕ амендить чужие коммиты — всегда новый коммит.
- НЕ убирать `data/` из `.gitignore`.
- НЕ перезаписывать всю `data/tasks.db` — это runtime state, ломаешь существующую работу пользователя.

---

**Этот файл — живой**. При добавлении новой папки / переименовании / новой ключевой фичи — обнови AGENTS.md в том же коммите.

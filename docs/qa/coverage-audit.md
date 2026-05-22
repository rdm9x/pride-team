# Coverage Audit — baseline E8.1

- **Дата**: 2026-05-21
- **Автор**: qa
- **Задача**: E8.1 (`task_id=19f154c764e2`)
- **Цель**: зафиксировать стартовую точку покрытия тестами перед E8.2 (добавление недостающих тестов).
- **Тулы**: `pytest 9.0.3` + `pytest-cov 7.1.0` + `coverage 7.14.0`, отдельный venv на каждый подпроект.

> Отчёт по html-репортам:
> - `mcp_сервер/htmlcov/index.html`
> - `дашборд/htmlcov/index.html`
> (обе папки в `.gitignore`).

---

## 1. Структура проекта

Монорепо из трёх Python-частей:

| Подпроект | Код | Тесты | Venv |
|---|---|---|---|
| `mcp_сервер/pride_tasks/` | MCP-канбан, SQLite, 8 tools | `mcp_сервер/tests/` | `mcp_сервер/.venv` |
| `дашборд/` (Flask) | `app.py` — UI + REST + менеджер subprocess'а тимлида | `дашборд/tests/` | `дашборд/.venv` |
| `smoke/` | Демо-функция `greet()` | `smoke/tests/` | (использует venv MCP) |

`pyproject.toml` обоих подпроектов уже декларирует `pytest-cov` в dev-зависимостях
(MCP — установлен, дашборд — мы доставили `uv pip install pytest-cov`). Корневой
`requirements-dev.txt` создан в этой же таске.

---

## 2. Общее покрытие — **baseline ≈ 52%**

| Подпроект | Statements | Missed | Coverage | Тестов |
|---|---:|---:|---:|---:|
| `mcp_сервер/pride_tasks/` | 760 | 340 | **55.3%** | 58 ✓ |
| `дашборд/app.py` | 528 | 275 | **47.9%** | 29 ✓ |
| `smoke/hello.py` (отдельно) | ~3 | 0 | 100% | 3 ✓ |
| **Итого (взвешенно)** | **1 288** | **615** | **52.3%** | **90 ✓** |

Все 90 тестов зелёные. Регресса нет.

Цель qa-роли (см. `роли/qa.md`): **>70%**. Разрыв ≈ 18 п.п., главный долг —
дашборд (нужно тащить с 48% до ~70%, это около 115 строк нового покрытия) и
неоттестированные модули `server.py`/`router.py`/`alerts.py` (220 stmt с 0%
покрытием).

---

## 3. Топ слабых файлов

### 3.1 MCP-сервер (`mcp_сервер/pride_tasks/…`)

| # | Файл | Stmt | Miss | % | Что не покрыто |
|---|---|---:|---:|---:|---|
| 1 | `alerts.py` | 75 | 75 | **0%** | весь модуль Telegram-алертов (`TelegramAlerter`, `from_env`, `load_env_file`) |
| 2 | `router.py` | 78 | 78 | **0%** | весь роутер задач — `pick()`, `pick_from_db()`, CLI `main()` |
| 3 | `server.py` | 67 | 67 | **0%** | MCP-обёртки tools + `stdio_server` запуск |
| 4 | `__main__.py` | 3 | 3 | **0%** | entrypoint модуля |
| 5 | `tools.py` | 143 | 49 | **65.7%** | error-ветки: `notify_dmitry`, `chat_post`/`chat_recent`, `add/remove/get_dependencies`, валидация пустых аргументов (строки 240–335) |
| 6 | `db.py` | 361 | 68 | **81.2%** | редкие пути: восстановление после `IntegrityError`, граничные кейсы зависимостей, цикл `auto_vacuum`, `list_chat_messages` пагинация |
| 7 | `models.py` | 32 | 0 | 100% | — |
| 8 | `__init__.py` | 1 | 0 | 100% | — |

### 3.2 Дашборд (`дашборд/app.py`)

528 строк в одном файле — это монолит, поэтому привожу разбивку по семантическим блокам.

| Блок (строки) | Покрытие | Содержимое |
|---|---|---|
| `_format_stream_event` + `_humanize_tool` (71–219) | **~0%** | парсинг stream-json событий Claude Code — нет ни одного теста |
| `_record_session_from_result` (227–270) | **0%** | запись токенов сессии в `claude_sessions` |
| `_start_backup_thread` (273–305) | **0%** | фоновый бэкап SQLite |
| `_stream_reader` (307–330) | **0%** | поток-читатель stdout subprocess'а |
| `_has_pending_work` / `_auto_can_start` / `_auto_monitor_loop` (332–388) | **0%** | автозапуск тимлида |
| `_start_team_process` / `_stop_team_process` / `_team_status` (390–483) | **0%** | управление subprocess'ом — критическая зона, ноль покрытия |
| `/api/team/*` endpoints (730–780) | **частично 0%** | start/stop/status/auto/stream — не пинаются в тестах |
| `/api/team/silence` (786–815) | **0%** | глушилка алертов |
| `/api/router/pick` (823–831) | **0%** | вызов роутера |
| `/api/chat` GET/POST (833–847) | **частично** | один happy-path |
| `/api/inbox` (851–887) | **частично** | inbox-логика для тимлида не покрыта целиком |
| `/healthz` (891–896) | покрыто |
| `main()` (898+) | **0%** | CLI запуск, ожидаемо |
| CRUD `/api/tasks/*` (527–724) | в основном **покрыто** | основной API дашборда — главный плюс существующей сюиты |

---

## 4. Главные пробелы (тематически)

1. **MCP-обёртки и stdio-цикл** (`server.py`, `__main__.py`) — нет ни одного теста, который бы поднимал MCP-сервер и проверял протокол.
2. **Router** (`router.py`) — алгоритм выбора следующей задачи для тимлида, 0% покрытия. Это бизнес-логика, не I/O — тесты пишутся легко на in-memory fixtures.
3. **Telegram-алерты** (`alerts.py`) — 0%. Нужны юнит-тесты с моком HTTP + интеграционный тест `from_env()` на разных комбинациях env-переменных.
4. **Менеджмент subprocess'а тимлида в дашборде** (`_start_team_process`/`_stop_team_process`/`_team_status` + `/api/team/*`) — это самая «опасная» зона: subprocess, threads, signals, файлы pid/log. Любая регрессия здесь = пользователь не может запустить тимлида с дашборда. Сейчас ноль покрытия.
5. **Stream-парсер событий Claude Code** (`_format_stream_event` + `_humanize_tool`) — 150+ строк парсинга JSON разных типов. Хорошо ложится на табличные параметрические тесты.
6. **Auto-monitor loop** (`_auto_monitor_loop`/`_auto_can_start`) — фоновый автозапуск тимлида. Не покрыт.
7. **Error-ветки в `tools.py`** — happy-path покрыт, но валидация пустых строк, ошибки БД, отсутствие env-переменных Telegram — нет.
8. **Backup-thread** (`_start_backup_thread`) — фоновый бэкап БД, не проверен.

---

## 5. План для E8.2 (приоритеты)

### P1 — критично для прод-стабильности (~6 файлов тестов, +~120 stmt покрытия)

| ID | Файл-цель | Что покрыть | Где жить |
|---|---|---|---|
| P1-1 | `mcp_сервер/pride_tasks/router.py` | `pick()` (приоритет/роль/блокировки) — табличный, 6–8 кейсов | `mcp_сервер/tests/test_router.py` |
| P1-2 | `mcp_сервер/pride_tasks/alerts.py` | `TelegramAlerter.send()` happy + 4xx/5xx; `from_env()` все ветки | `mcp_сервер/tests/test_alerts.py` |
| P1-3 | `дашборд/app.py` `_start_team_process` / `_stop_team_process` / `_team_status` | моком `subprocess.Popen` — happy, double-start, missing script, kill timeout | `дашборд/tests/test_team_process.py` |
| P1-4 | `дашборд/app.py` `/api/team/*` endpoints | `start`, `stop`, `status`, `auto`, через Flask test_client с моком | `дашборд/tests/test_team_api.py` |

Ожидаемый эффект: MCP с 55 → ~75%, дашборд с 48 → ~62%.

### P2 — важно, но не блокер (~3 файла тестов, +~70 stmt)

| ID | Файл-цель | Что покрыть |
|---|---|---|
| P2-1 | `дашборд/app.py` `_format_stream_event` / `_humanize_tool` | параметрический тест на 10–15 типов событий из реального лога |
| P2-2 | `дашборд/app.py` `_record_session_from_result` | проверка корректного суммирования input/cache токенов |
| P2-3 | `mcp_сервер/pride_tasks/tools.py` | error-ветки `notify_dmitry`, `chat_post`, `add_dependency` с пустыми аргументами |

### P3 — nice to have (~2 файла тестов, +~40 stmt)

| ID | Файл-цель | Что покрыть |
|---|---|---|
| P3-1 | `дашборд/app.py` auto-monitor / backup-thread | юнит-тест `_has_pending_work`, `_auto_can_start`; для backup — проверка что файл создаётся |
| P3-2 | `mcp_сервер/pride_tasks/server.py` | smoke-тест MCP stdio: запустить сервер сабпроцессом, послать `list_tools` запрос |
| P3-3 | `mcp_сервер/pride_tasks/db.py` остатки 19% | `IntegrityError`-восстановление, циклы зависимостей, vacuum |

Целевой суммарный coverage после E8.2 P1+P2: **≥ 70%** (соответствует требованию `роли/qa.md`).

---

## 6. Команды для воспроизведения

```bash
# MCP-сервер
cd mcp_сервер
.venv/bin/pytest --cov=pride_tasks --cov-report=term --cov-report=html tests/

# Дашборд
cd ../дашборд
.venv/bin/pytest --cov=app --cov-report=term --cov-report=html tests/

# Smoke (под MCP venv)
cd ..
mcp_сервер/.venv/bin/pytest smoke/tests/ -v
```

HTML-отчёты появятся в `mcp_сервер/htmlcov/` и `дашборд/htmlcov/`
(обе папки в `.gitignore`).

---

## 7. Найденные «по пути» наблюдения

Это не баги, а кандидаты в тех-долг:

- В `дашборд/.venv` отсутствовали `pytest-cov` и `coverage`, хотя `pyproject.toml` MCP их декларирует. После `uv pip install pytest-cov` всё встало. Стоит в `setup.py` доставлять `pytest-cov` и в дашборд (сейчас он ставит только `pytest + flask`).
- В корне не было `.gitignore` — теперь создан (htmlcov/.coverage/.venv/pycache).
- В корне не было `requirements-dev.txt` — теперь создан (на случай не-uv-окружения).
- 0% в `__main__.py` и `main()` ожидаемы (CLI entry-points), но желательно хотя бы smoke-вызов `python -m pride_tasks --help` для документации поведения.
- `pytest.ini` в корне ссылается только на `mcp_сервер/tests` — это нормально, но нужно отметить в README что corner-cases (дашборд, smoke) требуют отдельных команд (см. п. 6).

---

## 8. Definition of Done E8.1

- [x] `pytest --cov` прогнан в обоих подпроектах
- [x] Зафиксированы baseline-цифры (MCP 55%, дашборд 48%, агрегат 52%)
- [x] Топ-10 слабых мест выписан с конкретными строками
- [x] Приоритезированный план P1/P2/P3 для E8.2 готов
- [x] `htmlcov/` и `.coverage` добавлены в `.gitignore`
- [x] `requirements-dev.txt` создан в корне
- [ ] Коммит — **не делаем** (по условию задачи)

---

## Update 2026-05-21 (E8.2) — Coverage поднят до 83%

- **Задача**: `bb437c3a5186` (E8.2: Добавить unit-тесты до coverage 80%+)
- **Автор**: qa

### Финальные цифры

| Подпроект | Statements | Missed | Coverage | Тестов | Δ vs baseline |
|---|---:|---:|---:|---:|---:|
| `mcp_сервер/pride_tasks/` | 760 | 131 | **83%** | 118 ✓ | **+27.7 п.п.** |
| `дашборд/app.py` | 528 | 93 | **82%** | 116 ✓ | **+34.1 п.п.** |
| `smoke/hello.py` | ~3 | 0 | 100% | 3 ✓ | — |
| **Итого** | **1 288** | **224** | **82.6%** | **237 ✓** | **+30.3 п.п.** |

### По модулям (MCP)

| Файл | Baseline | После | Δ |
|---|---:|---:|---:|
| `alerts.py` | 0% | **100%** | +100 |
| `router.py` | 0% | **97%** | +97 |
| `tools.py` | 66% | **89%** | +23 |
| `db.py` | 81% | **88%** | +7 |
| `server.py` | 0% | 0% | — (нужны smoke-тесты MCP stdio, отложено в P3) |
| `__main__.py` | 0% | 0% | — (CLI entry, ожидаемо) |

### По модулям (Дашборд)

`app.py` — единый файл; раньше непокрытыми были блоки `_start/_stop_team_process`,
`_team_status`, `_format_stream_event`, `_humanize_tool`, `_record_session_from_result`,
`_has_pending_work`, `_auto_can_start`, `/api/team/*`, `/api/team/silence`,
`/api/router/pick`, `/api/inbox`. После E8.2 они покрыты тестами через
`subprocess.Popen`-моки и Flask `test_client`.

### Файлы тестов созданы (E8.2)

| Файл | Тестов | Что покрывает |
|---|---:|---|
| `mcp_сервер/tests/test_router.py` | 19 | все ветки `pick()` + `pick_from_db()` + CLI `main()` |
| `mcp_сервер/tests/test_alerts.py` | 26 | `TelegramAlerter` (send + http/network ошибки), `from_env`, `load_env_file` |
| `mcp_сервер/tests/test_tools_errors.py` | 15 | error-ветки `add_dependency`, `notify_dmitry`, `chat_post`/`chat_recent` |
| `дашборд/tests/test_team_process.py` | 57 | `_start/_stop_team_process`, `_team_status`, `_has_pending_work`, `_auto_can_start`, `_format_stream_event`, `_humanize_tool`, `_record_session_from_result` |
| `дашборд/tests/test_team_api.py` | 30 | `/api/team/*`, `/api/router/pick`, `/api/chat`, `/api/inbox`, `/api/usage`, зеркалирование комментов в чат |
| **Итого добавлено** | **147** | |

Все 237 тестов зелёные. Регресса по прежним 90 тестам нет.

### Что НЕ закрыто (заведомо)

- `mcp_сервер/pride_tasks/server.py` (0%) — MCP stdio-обёртки. Требуют либо
  поднятия сабпроцесса с протоколом, либо MCP test-harness. Отложено
  в P3 — не блокер прод-стабильности (это тонкая обёртка над уже
  покрытым `tools.py`).
- `__main__.py` (0%) — `python -m pride_tasks` entry-point, 3 строки.
- Хвосты `db.py` (12%) — редкие пути восстановления после IntegrityError,
  пагинация `list_chat_messages`. Низкий impact.

### Команды для воспроизведения (актуально)

```bash
# MCP
cd mcp_сервер
.venv/bin/pytest --cov=pride_tasks --cov-report=term --cov-report=html tests/

# Дашборд
cd ../дашборд
.venv/bin/pytest --cov=app --cov-report=term --cov-report=html tests/

# Smoke
cd ..
mcp_сервер/.venv/bin/pytest smoke/tests/ -v
```

HTML-отчёты обновлены в `mcp_сервер/htmlcov/` и `дашборд/htmlcov/`.

### Definition of Done E8.2

- [x] Coverage ≥ 80% (по `роли/qa.md` цель была 70%, фактически 82.6%)
- [x] Все тесты зелёные (237/237)
- [x] Регресса нет
- [x] `docs/qa/coverage-audit.md` обновлён финальными цифрами
- [x] Production-код не правился (только тесты)
- [ ] Коммит — **не делаем** (по условию задачи)

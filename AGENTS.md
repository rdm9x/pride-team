---
тип: карта_репозитория_для_агентов
проект: devboard
читать_первым: да
обновлено: 2026-05-24
версия: v2.0
---

# AGENTS.md — core карта репозитория Devboard

> Читай этот файл первым. Детали по каждому модулю — в `docs/AGENTS_EXTENDED.md`.
> Не делай `ls` для разведки — структура описана ниже.

---

## TL;DR что где живёт

| Папка | Что |
|---|---|
| `dashboard/` | Flask UI + REST API (port 4999). `app.py` ~1750 строк. |
| `mcp_server/` | MCP-сервер `devboard-tasks`. `tools.py` — 14 MCP-функций, `db.py` — SQLite. |
| `roles/` | System-prompts ролей (markdown с frontmatter). НЕ менять без задачи. |
| `commands/` | bash/ps1 скрипты: `devboard-start.sh`, `-stop`, `-work`, `-test` |
| `data/` | SQLite БД, бекапы, .env.local, team.log — **gitignored** |
| `docs/` | ADR / qa-отчёты / launch. `docs/AGENTS_EXTENDED.md` — полная карта. |
| `tests/` | top-level smoke. Также `dashboard/tests/` (~116) и `mcp_server/tests/` (~118). |
| `scripts/` | `stress_test.py`, `migrate_*.py` — DB-миграции |

---

## Где что править

| Задача | Файл |
|---|---|
| Новый REST endpoint | `dashboard/app.py` |
| Новая SPA view | `dashboard/templates/kanban.html` + `dashboard/static/app.js` |
| Новый i18n-ключ | `dashboard/static/i18n/ru.json` + `en.json` (синхронно!) |
| Новый MCP-tool | `mcp_server/devboard_tasks/tools.py` + регистрация в `server.py` |
| Роутер моделей | `mcp_server/devboard_tasks/router.py` + `mcp_server/tests/test_router.py` |
| Схема БД | `mcp_server/devboard_tasks/db.py` (SCHEMA_SQL + `ensure_dev_department`) + миграция в `scripts/` |
| Стили дашборда | `dashboard/static/style.css` |

---

## 14 MCP-tools (`mcp__devboard-tasks__*`)

`list_tasks` · `get_task` · `create_task` · `update_task` · `claim_task`
`add_comment` · `submit_result` · `list_roles`
`chat_recent` · `chat_post` · `notify_user`
`add_dependency` · `remove_dependency` · `get_dependencies`
`list_departments` · `get_department` · `create_department`

---

## Критичные правила (нарушение = баг)

1. **safety-net**: тимлид не может поставить `done` через MCP. `update_task`/`submit_result` с `status=done` → форсируется `review`. Обход только `_bypass_safety_net=True` (Flask UI). Label `night-auto` — explicit grant.
2. **Импорт `pride_tasks`** — через `sys.path.insert` в `dashboard/app.py:26-28`. Не трогать без понимания почему.
3. **БД в `.gitignore`** — `data/tasks.db` не коммитить. Новый пользователь получает чистую БД через `setup.py`.
4. **Порт 4999** — macOS AirPlay занимает 5000.
5. **i18n**: новый ключ — в оба файла (`ru.json` + `en.json`) синхронно.
6. **Изменения `app.py`** — требуют перезапуска дашборда. Статика (`*.js`, `*.css`) — нет.
7. **Субагент через Task tool не имеет MCP** — тимлид сам делает `update_task` после Task tool.
8. **model_hint** (S15.2) — опциональное поле задачи для hint роутеру (`opus`/`sonnet`/`haiku`). Не обязательно.

---

## Тесты

```bash
bash commands/devboard-test.sh      # все тесты
cd mcp_server && python -m pytest   # только MCP
cd dashboard && python -m pytest    # только дашборд
```

---

## НЕ делать

- НЕ создавать новые .md в корне без обсуждения.
- НЕ менять `dashboard/static/` без согласования с frontend.
- НЕ амендить чужие коммиты — только новый коммит.
- НЕ делать `git push` без approval.
- НЕ трогать роли (`roles/*.md`) без явной задачи.

---

> Полный контент (endpoints, LocalStorage keys, подводные камни, Windows UTF-8) — `docs/AGENTS_EXTENDED.md`.

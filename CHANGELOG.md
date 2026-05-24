# Changelog

All notable changes to **devboard** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2026-05-23

First multi-team release of **devboard**. The single-team kanban becomes a platform of AI departments, each with its own roles, kanban, and chat. Existing v1.x installs upgrade automatically via an idempotent migration that moves every existing task, role, and chat message into the default `dev` department. Three accepted ADRs lock in the design.

### Added

- **Departments (ADR-003).** New `departments` table; `department_id` foreign key on `tasks`, `roles`, and `chat_messages`. `NULL` is reserved for global rows — HR/owner roles and the inter-department audit channel. Indexes `(department_id, status)` keep per-department kanban queries cheap. Migration script `scripts/migrate_v2_departments.py` is atomic, idempotent, and supports `--rollback`. Three new MCP tools (`list_departments`, `get_department`, `create_department`); existing tools (`create_task`, `list_tasks`, `chat_post`, `chat_recent`) accept an optional `department_id` (default `'dev'`). REST endpoints: `GET /api/departments`, `GET /api/departments/<id>`, `POST /api/departments`, `PATCH /api/departments/<id>/archive`. `GET /api/tasks` and `GET /api/chat` honour `?department=<id>` and fall back to `dev`.
- **HR role + 5 department templates (ADR-004).** New global role `roles/hr.md` (`department_id = NULL`) — a meta-agent that creates departments from YAML templates via a chat-driven edit loop with the owner. Five MVP templates live in `templates/departments/`: `marketing-v1`, `design-v1`, `sales-v1`, `support-v1`, `operations-v1`. HR pipeline state machine (`idle → hr_planning → awaiting_owner_review → hr_revising → hr_activating → active`) with hard limits: max 8 roles per department, max 5 edit iterations, whitelisted models only, no destructive-labelled roles. Every generated role file carries `extras.hr_meta` (template_id, hr_session_id, customizations) for auditable history.
- **Inter-department workflow (ADR-005).** New columns `tasks.requester_department_id` and `tasks.requester_role_slug`. Only a department Lead (or owner) can create cross-department tasks via `POST /api/departments/<target>/tasks`; rank-and-file roles are blocked at both the REST layer and the MCP layer. The receiving Lead may **take** or **counter-propose** — there is no `Decline`. `P1`/`P2` priorities and `requires_budget`/`destructive` labels escalate to the owner's Inbox. Global append-only `inter_department_events` table with SQL triggers that reject UPDATE/DELETE. Capacity badges in the sidebar (`N in work, M in queue`), position-preview on cross-task creation; no ETA promises. Owner has two escape hatches: `priority-bump` and `admin-override`. Rate limit: 10 `P3` cross-tasks per 24h per (requester, target) pair.

### Migration

Upgrade from any v1.x to v2.0.0 is **automatic and idempotent**:

- The dashboard runs `scripts/migrate_v2_departments.py` on first start. It creates the `departments` table, inserts the default row `id='dev'`, adds the `department_id` column to `tasks`/`roles`/`chat_messages`, and backfills every existing row to `'dev'`. Global roles (`hr`, `owner`, `user`, `пользователь`) keep `department_id = NULL`.
- The migration is wrapped in a single transaction. If any step fails the database is left on v1.x.
- A `--rollback` mode restores from the auto-created `*.pre-v2.bak` backup.
- The v1.6 → v2.0 path is covered end-to-end by the smoke test `mcp_server/tests/test_v2_migration_smoke.py` (replays the anonymised fixture `tests/fixtures/v1.6_snapshot.db`, asserts no row counts change, asserts the second and third runs are no-ops).

See [`docs/migration-v2.md`](docs/migration-v2.md) for the full upgrade guide.

## [2.1.0] - 2026-05-24

Night-batch release: Windows reliability + tutorial + token optimization.
Includes all of v2.0.1, v2.0.2, and v2.1.0 changes landed via automated sprints S13–S15.

### Added
- **Token optimization (ADR-006)** (S15.1/S15.2): `chat_recent` default limit 50→10; `model_hint` optional field on tasks (DB column + MCP tools `create_task`/`update_task`/`list_tasks`/`get_task`); `AGENTS.md` split into core (~70 lines) + `docs/AGENTS_EXTENDED.md` (full reference); `ANTHROPIC_PROMPT_CACHING_ENABLED` comment in `devboard-work.sh`. Expected: −30–50% tokens/session (baseline $2.92 → target $1.80).
- **Tutorial вкладка /learn** — see v2.0.2 below.
- **Docker-first + Windows reliability** — see v2.0.1 below.

### Fixed
- `scripts/migrate_s15_model_hint.py` — idempotent standalone migration for existing DBs.

## [2.0.2] - 2026-05-24 (tutorial)

### Added
- **Tutorial вкладка /learn** (S14.1): двухколоночный layout (TOC 200px + long-read article), 5 страниц, localStorage для текущей страницы, re-render при смене локали, a11y + light/dark.
- **Контент: Введение + Как формулировать задачи** (S14.2): метафора виртуальных сотрудников, 5-шаговый workflow, ограничения; примеры хороших/плохих задач с `.example-good` / `.example-bad` стилизацией; EN + RU.
- **Контент: Отделы + HR** (S14.3): когда нужен отдел, как создать, шаблоны; бриф для HR с примерами good/bad, edit-loop; EN + RU.
- **Страница Shortcuts + wizard интеграция** (S14.4): таблица горячих клавиш (`Esc`, `Ctrl/Cmd+Enter`, `Ctrl/Cmd+K` coming soon); кнопка «Открыть обучение» в last step first-run wizard; кнопка Replay tutorial в Settings.

## [2.0.1] - 2026-05-24 (windows reliability)

### Added
- **Docker-first Quick Start** (S13.1): `docker compose up` инструкция в README.md, README.ru.md, README_WINDOWS.md как primary path; порт исправлен 5000→4999 в Dockerfile EXPOSE/HEALTHCHECK и docker-compose.yml ports/healthcheck.
- **Windows diagnostic mode** (S13.2): `"Запустить devboard.bat" --diag` — печатает Python/OS/encoding/venv/ExecutionPolicy без запуска дашборда.
- **Cross-platform troubleshooting guide** (S13.3): `docs/INSTALL_TROUBLESHOOTING.md` — гайд по типичным ошибкам install на Windows/macOS/Linux.

### Fixed
- **setup.py Windows UTF-8** (S13.2): `sys.stdout.reconfigure(encoding="utf-8")` под `IS_WINDOWS` guard; `PYTHONIOENCODING=utf-8` + `PYTHONUTF8=1` propagated во все дочерние subprocess через `run()` helper.
- **ExecutionPolicy** (S13.2): батник автоматически делает `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` при запуске.
- **Error message Python not found** (S13.2): добавлена ссылка на python.org/downloads с явной инструкцией про галочку "Add Python 3.x to PATH".
- **CRLF protection** (S13.3): `.gitattributes` — `*.sh eol=lf`, `*.ps1 eol=crlf`, `*.py eol=lf`; устраняет `bad interpreter ^M` при клонировании на Windows с `autocrlf=true`.
- **HR subprocess encoding** (S13.3): `dashboard/hr.py::spawn_hr_subprocess` — добавлены `encoding="utf-8"`, `errors="replace"` и `env["PYTHONUTF8"]="1"`; кириллица в HR-сессиях на Windows больше не превращается в мусор.
- **devboard-start.ps1 hardcoded port** (S13.3): заменён `5000` на `$env:PRIDE_DASHBOARD_PORT` (по умолчанию `4999`) в сообщении «already running».
- **devboard-work.ps1 feature parity** (S13.3): добавлены output_locale (`data/.output_locale` → `LANG_PROMPT`), user_expertise (`data/.user_expertise` → `DEVBOARD_USER_EXPERTISE`), ветка `non-tech` с `$ExpertisePrompt`; паритет с `.sh`-версией достигнут.

## [Unreleased] / v2.0-alpha.1 (departments backend)

### Added

- **Departments data model** (S8.1, ADR-003): new `departments` table in SQLite; `department_id` column added to `tasks`, `roles`, `chat_messages`; `ensure_dev_department()` migrates all existing data to the default `dev` department; `scripts/migrate_v2_departments.py` with idempotent run and `--rollback` support.
- **MCP-tools: department support** (S8.2): `create_task`, `list_tasks`, `chat_post`, `chat_recent` accept optional `department_id` (default `'dev'`); three new tools — `list_departments`, `get_department`, `create_department`.
- **REST API: /api/departments** (S8.3): `GET /api/departments`, `GET /api/departments/<id>`, `POST /api/departments`, `PATCH /api/departments/<id>/archive`; `GET /api/tasks` and `GET /api/chat` now accept `?department=<id>` with backward-compatible fallback to `'dev'`.

## [Unreleased] / v1.6 (local)

### Fixed

- **Statistics layout regression** (S6.1): restored original KPI grid layout broken by S5.2. Lifetime counters moved into a dedicated `#statsLifetime` section at the top with new `.lifetime-counter-grid` / `.lifetime-counter-card` classes (4 cards in a row, 2×2 on ≤768 px, colour-coded: green / blue / accent / yellow). Existing sections (models, roles, heatmap) unchanged.
- **Task modal reader-mode v2** (S6.2): complete rewrite of task detail overlay. Shows TL;DR prominently (18 px, accent border-left), inline option-buttons for numbered choices (click posts a comment), acceptance checklist with localStorage state, and a collapsible "Technical details" section. Fallback to plain markdown for tasks without TL;DR. 6 i18n keys added. New `test_task_parser.py` (6 tests).

## [Unreleased] / v1.5 (local)

### Added

- **First-run wizard** (S5.3): full-screen overlay on first open — 4 steps (language, expertise level, theme, done). Saves `ui_locale`, `output_locale`, `user_expertise`, `devboard-theme` to localStorage. Launches onboarding tour automatically after completion. Settings → Danger zone: reset/restart buttons.
- **Expanded onboarding tour** (S5.4): 12 steps covering all 6 nav-items (Board, Inbox, Statistics, Roles, Archive, Settings), topbar controls (Start, Auto mode), and chat panel. Replaces the previous 5-step tour.
- **Task reader-mode** (S5.5): task modal now shows structured view — large TL;DR, steps checklist, acceptance checklist, and inline answer buttons for option questions. Raw markdown collapsed under "Technical details" toggle. Backend: `GET /api/tasks/<id>/parsed` endpoint.
- **Statistics lifetime counters** (S5.2): 4 large KPI cards (tasks done, total created, completion rate %, in progress) always shown across full history including archived tasks. Count-up animation on render.

### Fixed

- **Statistics haiku model** (S5.1): `COALESCE(SUM(total_cost_usd), 0.0)` prevents `TypeError` crash in stats endpoint when haiku sessions have `NULL` cost — all models including `claude-haiku-4-5-20251001` now appear in the models breakdown.
- **Inbox nav label** (S5.7): RU sidebar nav label «Inbox» → «На столе»; EN unchanged.
- **Inbox group height** (S5.7): `.inbox-groups { align-items: start }` — each group sizes to its own content instead of stretching to match the tallest group.

## [Unreleased] / v1.4 (local)

### Added

- **i18n coverage** (S4.1): wrapped ~28 hardcoded Russian `title`/`aria-label`/`placeholder` attributes in `kanban.html` and `app.js` with `data-i18n-attr` — all tooltips now follow UI locale.
- **`name_en` in example roles** (S4.8): all 6 `roles/examples/*.md` now have `name_en` and `slug` frontmatter fields; passes role validator.
- **AGENTS.md caveats** (S4.6): added 4 entries to "Частые подводные камни" — Settings, Statistics, i18n public API, plain-language mode.
- **README features** (S4.4): `README.md` and `README.ru.md` now mention Settings tab, Statistics tab, dual-language i18n, and plain-language mode.

### Changed

- **Port unified to 4999** (S4.3): `dashboard/app.py` default, `.env.example`, `devboard-start.sh`, `README.md`, `README.ru.md`, `CONTRIBUTING.md`, `DEPLOYMENT.md`, `README_WINDOWS.md`, `setup.py`, `docs/launch/devto-post.md`.
- **Error responses** (S4.2): backend (`app.py`, `tools.py`) now returns both `{"причина": …, "reason": …}` dual-key; frontend reads `err.причина || err.reason`.
- **`ARCHITECTURE.md`** (S4.5): ADR-002 → Accepted, new endpoints (`/api/settings/static-info`, `/api/stats/aggregates`, `/api/demo`), `name_en` mentioned in roles frontmatter section.

### Fixed

- **Stale path refs** (S4.7): removed all `/D.AI/команда` from docstrings/comments in `app.py`, `server.py`, `db.py`, `devboard-work.sh`, `roles/*.md`, `approval_gates.md`.
- **Orphaned TODO** (S4.9): removed `TODO(E2.3)` comment from `locale-switcher.js` — `i18n-loader.js` (E2.3) is long done.

## [Unreleased] / v1.3 (local)

### Added

- **Statistics tab** (S3.2): new sidebar entry with 5 sections — KPI cards (sessions, turns, cost, files, lines, hours), model breakdown table with inline bars, role activity bars, 24h hourly heatmap, top achievements. Zero external dependencies; vanilla CSS animations. Backend: `GET /api/stats/aggregates?range=today|24h|week|all` with 60s cache.
- **Sidebar reorder** (S3.3): Board → Inbox → Statistics → Roles → Archive → Settings. Default view on first load is Board; `last_view` persisted in localStorage.
- **Plain-language mode** (S3.4): `user_expertise` toggle in Settings (Developer / Non-developer). Stored in `localStorage`; sent to `POST /api/team/start`; saved in `data/.user_expertise`; read by `commands/devboard-work.sh` which adds a `--append-system-prompt` block for non-technical users.

### Removed

- **Usage section from Settings** (S3.1): moved to the dedicated Statistics tab. Settings now has 5 sections (Language / Theme / Team / Backups / Danger zone).

## [Unreleased] / v1.2 (local)

### Added

- **Settings page** (S2.1): full settings tab with 6 sections — Language, Theme, Team, Backups, Usage, Danger zone. Replaces the read-only "Status" sidebar item.
- **Dual-axis i18n** (S2.2): separate `ui_locale` (interface language) and `output_locale` (team chat/task language). Output locale stored in `data/.output_locale` and injected into claude via `--append-system-prompt`.
- **EN role names** (S2.3): roles display as `Team Lead / Backend / QA / Architect / Frontend / DevOps / Tech Writer` when `ui_locale=en`. Resolved via `ROLE_DISPLAY` map in `app.js`; `name_en` frontmatter added to all `roles/*.md`.
- **Chat UX** (S2.4): auto-scroll to bottom on load; floating ⬇ button with unread badge when scrolled up; auto-scroll on new messages if already at bottom.

### Fixed

- `.gitignore`: added `data/.env.local` and `data/.output_locale` to prevent accidental credential/runtime-state commits.

## [1.1.0] - 2026-05-22

### Changed

- Product renamed: `pride-team` → `devboard` across the entire repo (sidebar brand, README, packages, configs, launcher scripts).
- Owner role renamed: `пользователь`/`пользователь` → `пользователь`/`user` in code, i18n, tests, and DB migration script (`scripts/migrate_user_to_user.py`) for open-source friendliness.
- i18n RU: todo column label "К работе" → "В очереди".

### Fixed

- CSS: scrollbar in kanban columns no longer overlaps card borders (`padding-right: 8px; scrollbar-gutter: stable` on `.column .cards`).
- CSS: column header no longer hidden by top-card hover transform (`position: sticky; z-index: 2` on `.column h2`).

## [1.0.0] - Unreleased

First public release. Open-source baseline of devboard — a local kanban driven by a small fleet of AI role-bots (Team Lead, Backend, QA, and optional specialists).

### Added

- MIT `LICENSE` and `NOTICE` files at the repository root.
- Top-level `.gitignore` covering `.env`, virtualenvs, build artifacts, IDE files, and SQLite WAL/SHM siblings.
- `gitleaks` audit run on the full git history; no secrets leaked.
- English UI with runtime i18n switcher backed by `static/i18n/{ru,en}.json`.
- Onboarding tour: 5-step first-run popovers across kanban, task detail, run-team, approvals, and chat.
- Empty-state illustrations and copy for empty kanban columns and chat thread.
- Demo mode: one-click seeding of a sample task graph for first-time exploration.
- `README.md` rewritten as the public landing page (quickstart, screenshots placeholder, roles, configuration, architecture-at-a-glance).
- `CONTRIBUTING.md` covering setup, code style, branching, adding roles and LLM providers, testing, and PR process.
- `ARCHITECTURE.md` with component diagram, data model, and three end-to-end flow diagrams (create task, run team, approval gate).
- `CHANGELOG.md` (this file) in Keep a Changelog 1.1.0 format.
- Issue and pull request templates under `.github/`.
- `Dockerfile` and `docker-compose.yml` for VPS deployment; image runs as a non-root user.
- GitHub Actions CI workflow: `ruff check`, `mypy`, and `pytest` on every push and pull request.
- Multi-LLM support via `LLMProvider` abstraction with Claude, OpenAI, and Ollama backends (see [ADR-001](docs/adr/0001-llm-provider.md)).
- Per-role provider/model selection through YAML frontmatter (`llm`, `model`, `temperature`, `max_tokens`) in `roles/*.md` (see [ADR-002](docs/adr/0002-role-format.md)).
- Configurable roles: load any `roles/<name>.md` without code changes; strict frontmatter validation with clear `RoleConfigError` messages.
- Role marketplace v0: import a role from a remote URL into the local `roles/` directory.
- UI for adding, editing, and deleting roles from the dashboard *Roles* page.
- Five example community roles shipped under `roles/examples/`: Product Manager, Designer, Security Auditor, Code Reviewer, Data Analyst.
- Per-role MCP tool allowlist (`tools:` field) — declarative allowlist enforced at subagent spawn.
- Unit and integration test suites under `mcp_сервер/tests/`, `дашборд/tests/`, and `smoke/tests/`.
- Coverage reporting via `pytest-cov`; baseline coverage threshold enforced in CI.
- `.pre-commit-config.yaml` wiring `ruff`, `mypy`, and `gitleaks` to run before every commit.
- Stress test for the kanban write path — eight concurrent writers against `fcntl` + `BEGIN IMMEDIATE`, asserts no lost updates and no `database is locked` errors.

### Changed

- Renamed Cyrillic source folders to Latin equivalents for cross-platform tooling:
  `роли/` → `roles/`, `дашборд/` → `dashboard/`, `команды/` → `commands/`, `мcp_сервер/` → `mcp_server/`.
- Launcher scripts renamed to Latin: `devboard-start.sh`, `devboard-work.sh`, and their Windows `.ps1`/`.bat` counterparts.
- Internal module imports and `pyproject.toml` package paths updated to match the new folder names.
- Default UI language is now English; Russian remains available via the in-app language switcher.
- Team Lead invocation goes through `create_provider()` instead of a hard-coded `claude --print` call.
- Role files now require explicit `schema_version: 1` frontmatter; existing roles migrated.
- Dashboard *Roles* page shows the new `name` / `description` / `llm` / `model` fields and the per-role tool allowlist.

### Fixed

- Race condition in `_atomic_modify` where a stale `fcntl` lock could persist after an abnormal exit; lock file is now cleaned up on startup.
- Stream-json parser no longer crashes on partial UTF-8 fragments split across SSE chunks.
- Backup thread now exits cleanly on `SIGTERM`; previously could leave a half-written `.backup` snapshot.

### Security

- `gitleaks` audit run against the full git history before the public release — no secrets leaked.
- `.env`, `.env.*`, and `*.key` patterns added to `.gitignore`.
- Docker image runs as a non-root user (`uid 1000`) with a read-only root filesystem where possible.
- Approval-gated operations (`git push`, `ssh`, `systemctl restart`, destructive shell commands) cannot be executed by subagents directly; they must go through the human approval flow documented in `approval_gates.md`.
- CI runs `gitleaks` and `pip-audit` on every pull request.
- All third-party LLM SDKs are imported lazily inside their provider modules so a user who does not need a given provider is not forced to install its dependencies.

<!--
When releasing:
1. Replace [Unreleased] with [X.Y.Z] - YYYY-MM-DD
2. Add an empty [Unreleased] section at the top with Added/Changed/Fixed/Security headings
3. Bump the version in setup.py / pyproject.toml
4. Create an annotated git tag vX.Y.Z and push it
5. Cut a GitHub release using the new section as the release notes body
-->

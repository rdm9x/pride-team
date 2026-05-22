# Changelog

All notable changes to **devboard** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

### Changed

### Fixed

### Security

## [1.1.0] - 2026-05-22

### Changed

- Product renamed: `pride-team` → `devboard` across the entire repo (sidebar brand, README, packages, configs, launcher scripts).
- Owner role renamed: `Дмитрий`/`дмитрий` → `пользователь`/`user` in code, i18n, tests, and DB migration script (`scripts/migrate_dmitry_to_user.py`) for open-source friendliness.
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

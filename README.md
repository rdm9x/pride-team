# pride-team

> An AI dev team in your kanban.

[![CI](https://img.shields.io/badge/CI-pending-lightgrey)](#)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Stars](https://img.shields.io/github/stars/pride-team/pride-team?style=social)](#)

Three role-bots — **Team Lead**, **Backend**, **QA** — share one local kanban and ship real code while you watch the board. You write the task; they pick it up, decompose it, write the code, run the tests, and hand it back for approval.

<!-- video demo will go here after E9 -->
<img alt="pride-team demo (placeholder — replaced after E9)" src="docs/screenshots/demo.gif" width="720" onerror="this.style.display='none'"/>

## Why

Most coding agents run as a single loop in your terminal. `pride-team` runs as a **small org**: a Team Lead splits work, delegates to specialists, reviews their results, and only escalates to you when it actually matters. Everything lives in a SQLite kanban you can read with `sqlite3` and see in a Flask dashboard.

Built for solo developers who want agent-driven delivery without giving up the board, the audit trail, or the approval gates.

## Quickstart

**Requirements:** Python 3.11+, an Anthropic subscription with `claude` CLI installed.

### Option A — double-click (Mac / Linux / Windows)

```text
Запустить pride-team.command   # macOS / Linux (double-click in Finder)
Запустить pride-team.bat       # Windows       (double-click in Explorer)
```

The launcher installs dependencies on first run, starts the Flask dashboard, and opens `http://127.0.0.1:5000` in your browser.

### Option B — shell

```bash
git clone https://github.com/pride-team/pride-team.git
cd pride-team
python3 setup.py            # one-time: creates venvs, installs deps
./команды/pride-team-start.sh
open http://127.0.0.1:5000
```

### Option C — Docker

```bash
cp .env.example .env
# edit .env, set ANTHROPIC_API_KEY (or OPENAI_API_KEY / OLLAMA_URL)
docker compose up -d
open http://localhost:5000
```

Data lives in `./data` (bind-mounted into the container) and survives
restarts. See [DEPLOYMENT.md](DEPLOYMENT.md) for a full VPS guide.

Once the dashboard is up:

1. Click **+ New task**, fill the form, save — the task lands in **TO DO**.
2. Click **▶ Run team** in the header. The Team Lead picks up the task, decomposes it, delegates subtasks to Backend and QA, and streams live output to the bottom panel.
3. When a task moves to **REVIEW**, open the card and click **Accept** or **Send back**.
4. When you see a task in **NEEDS APPROVAL ⚠**, open it, read what the agent wants to do, and click **Approve** or **Reject**.

## Screenshots

<!-- screenshot: kanban view -->
<!-- screenshot: task detail with live log -->
<!-- screenshot: approval gate modal -->
<!-- screenshot: roles page -->

Real screenshots land in `docs/screenshots/` as part of **E4.6**.

## Roles

Each role lives as a system prompt in [`роли/`](роли/):

| File | Role | Tools |
|---|---|---|
| `роли/тимлид.md` | Team Lead — plans, decomposes, reviews, escalates | MCP `pride-tasks` + Task (subagents) + Read / Bash / Edit |
| `роли/бэкенд.md` | Backend — writes code, unit tests | Read / Write / Edit, Bash, MCP `pride-tasks` (read + comment + submit) |
| `роли/qa.md` | QA — runs tests, finds regressions, writes new tests | Read, Bash, MCP `pride-tasks` |
| `роли/архитектор.md` | Architect (optional) | Read, MCP `pride-tasks` |
| `роли/frontend.md` | Frontend (optional) | Read / Write / Edit, Bash |
| `роли/devops.md` | DevOps (optional) | Read, Bash, approval-gated shell |
| `роли/техписатель.md` | Tech Writer (optional) | Read / Write / Edit on docs only |

Architecture details live in [ARCHITECTURE.md](ARCHITECTURE.md) (added in **E4.3**).

## Configuration

Set these in `.env` or your shell before launching.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | yes | — | Auth for the Team Lead and subagents. Subscription tokens via `claude` CLI also work. |
| `PRIDE_DASHBOARD_PORT` | no | `5000` | Flask dashboard port. |
| `PRIDE_DB_PATH` | no | `data/tasks.db` | SQLite kanban location. |
| `OPENAI_API_KEY` | no | — | Optional fallback model for cost-sensitive subtasks. |
| `OLLAMA_URL` | no | — | Optional local model endpoint, e.g. `http://localhost:11434`. |
| `CLAUDE_MODEL` | no | `opus` | Model for the Team Lead. |

## Architecture at a glance

```text
You ── kanban form ──► Flask dashboard ── SQLite (tasks.db) ◄── MCP `pride-tasks`
                                              ▲
                                              │ live log (SSE)
                                              │
                            claude -p  ──► Team Lead
                                              │ Task tool
                                              ├──► Backend subagent
                                              └──► QA subagent
```

- **Atomic writes:** `fcntl` lock + SQLite `BEGIN IMMEDIATE`. Eight concurrent writers tested.
- **MCP server** runs as a stdio process inside the Claude session, configured via `.mcp.json`.
- **Approval gates** (`git push`, `ssh`, `systemctl restart`, etc.) require explicit user approval — see [approval_gates.md](approval_gates.md).

## Roadmap

- **E1** — MCP server `pride-tasks` (done)
- **E2** — Flask dashboard + live log (done)
- **E3** — Approval-gate workflow (done)
- **E4** — Documentation pass (in progress — this README is **E4.1**)
- **E5** — `docker-compose` packaging
- **E6** — CI / GitHub Actions
- **E7** — Multi-model fallback (OpenAI, Ollama)
- **E8** — Bitrix24 bridge → `pride-dev-department`
- **E9** — Video demo + landing page

## Contributing

PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) (added in **E4.2**).

## License

[MIT](LICENSE) © 2026 Dmitry Rudich.

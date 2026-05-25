# devboard

> An AI dev team in your kanban.

[![CI](https://img.shields.io/badge/CI-pending-lightgrey)](#)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Stars](https://img.shields.io/github/stars/devboard/devboard?style=social)](#)

Three role-bots — **Team Lead**, **Backend**, **QA** — share one local kanban and ship real code while you watch the board. You write the task; they pick it up, decompose it, write the code, run the tests, and hand it back for approval.

<!-- video demo will go here after E9 -->
<img alt="devboard demo (placeholder — replaced after E9)" src="docs/screenshots/demo.gif" width="720" onerror="this.style.display='none'"/>

## Quick Start (recommended)

```bash
git clone https://github.com/rdm9x/devboard.git
cd devboard
cp .env.example .env
# Open .env and set ANTHROPIC_API_KEY
docker compose up
# Open http://localhost:4999
```

Works the same on **Windows / macOS / Linux**. Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/).

Data lives in `./data` (bind-mounted into the container) and survives restarts and image rebuilds.

Once the dashboard is up:

1. Click **+ New task**, fill the form, save — the task lands in **TO DO**.
2. Click **▶ Run team** in the header. The Team Lead picks up the task, decomposes it, delegates subtasks to Backend and QA, and streams live output to the bottom panel.
3. When a task moves to **REVIEW**, open the card and click **Accept** or **Send back**.
4. When you see a task in **NEEDS APPROVAL ⚠**, open it, read what the agent wants to do, and click **Approve** or **Reject**.

See [DEPLOYMENT.md](DEPLOYMENT.md) for a full VPS guide.

---

## Manual install (without Docker)

> Use this path if Docker is not available. Requires Python 3.11+ and an Anthropic subscription with `claude` CLI.

### Option A — double-click (Mac / Linux / Windows)

```text
Запустить devboard.command   # macOS / Linux (double-click in Finder)
Запустить devboard.bat       # Windows       (double-click in Explorer)
```

The launcher installs dependencies on first run, starts the Flask dashboard, and opens `http://127.0.0.1:4999` in your browser.

### Option B — shell

```bash
git clone https://github.com/rdm9x/devboard.git
cd devboard
python3 setup.py            # one-time: creates venvs, installs deps
./команды/devboard-start.sh
open http://127.0.0.1:4999
```

---

## Why

Most coding agents run as a single loop in your terminal. `devboard` runs as a **small org**: a Team Lead splits work, delegates to specialists, reviews their results, and only escalates to you when it actually matters. Everything lives in a SQLite kanban you can read with `sqlite3` and see in a Flask dashboard.

Built for solo developers who want agent-driven delivery without giving up the board, the audit trail, or the approval gates.

## Features

- **Kanban board** — tasks move through TO DO → WIP → NEEDS APPROVAL → REVIEW → DONE. You approve risky operations; agents handle the rest.
- **Live log** — stream-json from the Claude session is parsed into human-readable lines and pushed to the browser via SSE.
- **Approval gates** — `git push`, `ssh`, `systemctl restart`, and other risky operations require explicit user approval before any agent runs them.
- **Model router** — picks `haiku`, `sonnet`, or `opus` based on task complexity. No tokens wasted on routing.
- **Settings tab** — configure language, teamlead mode, and model preferences in-dashboard. No manual `.env` edits needed for common options.
- **Statistics tab** — task throughput, team velocity, and role performance analytics, all from the same SQLite data.
- **Dual-language i18n** — both the dashboard UI and agent output switch between RU and EN. One toggle covers everything.
- **Plain-language mode** — the Team Lead simplifies its output for non-technical product owners. Toggle in Settings; no prompt editing required.
- **Multi-role team** — Team Lead, Backend, QA ship by default. Architect, Frontend, DevOps, and Tech Writer roles are drop-in extras.

## Multi-team mode (v2.0)

Devboard v2.0 turns the single-team kanban into a **multi-department platform**. One instance can host several departments — `Dev`, `Marketing`, `Design`, `Sales`, `Support`, `Operations` — each with its own kanban, its own roles, and its own per-department chat. The current department is stored in `localStorage` and sent on every request via the `X-Department` header; legacy `/api/tasks` and `/api/chat` calls fall back to `dev` so v1.x clients keep working.

A new global **HR role** spawns new departments through a chat-driven pipeline. HR picks the closest of five built-in YAML templates (`marketing-v1`, `design-v1`, `sales-v1`, `support-v1`, `operations-v1`), customises it for you in a 1–5 turn edit loop, and writes the role files only after you approve. All audit lives in `extras.hr_meta` of each generated role and in the `hr_sessions` table.

Departments coordinate through a strict **Lead-to-Lead inter-department workflow**. Only a department Lead (or owner) can post a cross-department task via `POST /api/departments/<target>/tasks`. The receiving Lead may take the task into queue or counter-propose — there is no *Decline*. `P1`/`P2` cross-tasks and anything labelled `requires_budget` escalate to the owner's Inbox. A global append-only `inter-department` channel records every cross-task event.

```mermaid
graph TB
  owner((Owner<br/>global))
  hr[HR Role<br/>department_id = NULL<br/>creates departments]
  dev_dept[Department: dev<br/>Team Lead, Backend, QA,<br/>Architect, Frontend,<br/>DevOps, Tech Writer]
  mkt_dept[Department: marketing<br/>Marketing Lead, Content Writer,<br/>SEO Researcher, SMM]
  design_dept[Department: design<br/>Design Lead, UI, Visual, UX]
  ops_dept[Department: operations<br/>Ops Lead, Analyst, Automation]
  inter_chat{{Inter-department channel<br/>department_id = NULL<br/>append-only audit log}}

  owner -- creates --> hr
  hr -- spawns --> mkt_dept
  hr -- spawns --> design_dept
  hr -- spawns --> ops_dept
  owner -. owns .-> dev_dept
  owner -. owns .-> mkt_dept
  owner -. owns .-> design_dept
  owner -. owns .-> ops_dept

  dev_dept -- Lead-to-Lead --> mkt_dept
  mkt_dept -- Lead-to-Lead --> design_dept
  design_dept -- Lead-to-Lead --> dev_dept

  dev_dept -.events.-> inter_chat
  mkt_dept -.events.-> inter_chat
  design_dept -.events.-> inter_chat
  ops_dept -.events.-> inter_chat
  inter_chat -.read by.-> owner
```

Design rationale lives in three ADRs: [ADR-003](docs/adr/0003-departments.md) (data model), [ADR-004](docs/adr/0004-hr-role.md) (HR role), [ADR-005](docs/adr/0005-inter-department.md) (cross-department workflow).

Upgrading from v1.x? See the **[v2 migration guide](docs/migration-v2.md)** — the migration is automatic, idempotent, and preserves every existing task, role, and chat message under `department_id = 'dev'`.

## Screenshots

<p align="center">
  <img src="docs/screenshots/01-kanban.png" alt="Kanban board with TODO / WIP / NEEDS APPROVAL / REVIEW / DONE columns" width="49%"/>
  <img src="docs/screenshots/02-chat.png" alt="Chat panel — direct messaging with the Team Lead" width="49%"/>
</p>
<p align="center">
  <img src="docs/screenshots/03-approval-gate.png" alt="Approval gate modal for destructive operations" width="49%"/>
  <img src="docs/screenshots/04-new-task.png" alt="New task form" width="49%"/>
</p>

## Roles

Each role lives as a system prompt in [`роли/`](роли/):

| File | Role | Tools |
|---|---|---|
| `roles/dev/lead.md` | Dev Lead — plans, decomposes, reviews, escalates | MCP `pride-tasks` + Task (subagents) + Read / Bash / Edit |
| `роли/бэкенд.md` | Backend — writes code, unit tests | Read / Write / Edit, Bash, MCP `pride-tasks` (read + comment + submit) |
| `роли/qa.md` | QA — runs tests, finds regressions, writes new tests | Read, Bash, MCP `pride-tasks` |
| `роли/архитектор.md` | Architect (optional) | Read, MCP `pride-tasks` |
| `роли/frontend.md` | Frontend (optional) | Read / Write / Edit, Bash |
| `роли/devops.md` | DevOps (optional) | Read, Bash, approval-gated shell |
| `роли/техписатель.md` | Tech Writer (optional) | Read / Write / Edit on docs only |

Architecture details live in [ARCHITECTURE.md](ARCHITECTURE.md) (added in **E4.3**).

## Configuration

Language, teamlead mode, and model preference can be changed in the **Settings tab** inside the dashboard — no file editing needed for common options.

For lower-level setup, set these in `.env` or your shell before launching.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | yes | — | Auth for the Team Lead and subagents. Subscription tokens via `claude` CLI also work. |
| `PRIDE_DASHBOARD_PORT` | no | `4999` | Flask dashboard port. |
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

[MIT](LICENSE) © 2026 owner.

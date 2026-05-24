# Migrating from v1.x to v2.0

devboard 2.0 introduces **departments** — the same kanban, the same roles, the same chat, but partitioned by a new `department_id` column. Upgrading is automatic. You do not edit SQL, you do not rewrite role files, you do not change your scripts.

This document covers:

1. What changes on disk and in the database.
2. How to upgrade.
3. How to roll back.
4. How v1.x clients keep working.
5. How to verify the migration.

---

## TL;DR

```bash
git pull                              # check out v2.0
./commands/devboard-start.sh          # migration runs on first start
open http://127.0.0.1:4999            # you should see your old kanban under "Dev"
```

If the dashboard starts and your old tasks appear in the **Dev** department, you are done.

---

## What changes

### Database schema

The migration adds:

| Object | Kind | Notes |
|---|---|---|
| `departments` table | new | Stores `id`, `name`, `description`, `template_id`, `hr_session_id`, `created_at`, `archived_at`. |
| `schema_meta` table | new | Single row `version = 'v2.0-departments'` — guards against re-running the migration. |
| `tasks.department_id` | new column | Foreign key to `departments(id)`. |
| `roles.department_id` | new column | Foreign key to `departments(id)`. `NULL` for global roles (`hr`, `owner`, `user`, `пользователь`). |
| `chat_messages.department_id` | new column | Foreign key to `departments(id)`. `NULL` is reserved for the global inter-department audit channel. |
| `idx_tasks_department`, `idx_tasks_dept_status`, `idx_roles_department`, `idx_chat_messages_department` | new indexes | Keep per-department queries cheap. |

No existing column is dropped, renamed, or retyped. No row is deleted.

### Backfill rules

The migration runs five `UPDATE` statements inside one transaction:

- **`departments`** receives one row: `id = 'dev'`, `name = 'Dev'`, `template_id = NULL`.
- **`tasks.department_id`** is set to `'dev'` for every row.
- **`chat_messages.department_id`** is set to `'dev'` for every row.
- **`roles.department_id`** is set to `'dev'` for every row **except** the global roles (`hr`, `owner`, `user`, `пользователь`), which keep `NULL`.
- **`schema_meta.version`** is set to `'v2.0-departments'`.

If the transaction fails at any step, the entire migration rolls back and the database is left on v1.x. A backup snapshot (`tasks.db.pre-v2.bak`) is created before the transaction starts.

### Files

- `roles/hr.md` — the new global HR role. v1.x role files are not touched.
- `templates/departments/*.yaml` — five built-in department templates (`marketing-v1`, `design-v1`, `sales-v1`, `support-v1`, `operations-v1`). Read-only baseline used by HR.

---

## How to upgrade

The migration is run automatically by the dashboard on first start. You do not need to invoke it by hand.

### Option A — automatic (recommended)

```bash
git pull
./commands/devboard-start.sh
```

The dashboard checks `schema_meta.version` on startup. If it is missing or not equal to `v2.0-departments`, the dashboard runs `scripts/migrate_v2_departments.py` against `data/tasks.db` before serving the first request.

You will see a single line in `data/dashboard.log`:

```
[migrate-v2] backfilled N tasks / M roles / K chat messages → department 'dev'
[migrate-v2] schema_meta.version = v2.0-departments
```

### Option B — manual

If you want to run the migration in advance (for example, before pushing v2.0 to a server you cannot stop), call the script directly:

```bash
PRIDE_TASKS_DB=/absolute/path/to/data/tasks.db \
  python scripts/migrate_v2_departments.py
```

The script is **idempotent**: running it a second time is a no-op and prints `Миграция уже выполнена`. The smoke test `mcp_server/tests/test_v2_migration_smoke.py` runs it three times in a row and asserts row counts do not change.

### Pre-flight checks

Before touching the database the script:

1. Reads `schema_meta.version`. If it equals `v2.0-departments`, the script exits with `0` and prints `Миграция уже выполнена`.
2. Verifies that `tasks`, `roles`, and `chat_messages` exist (sanity check for a real v1.x database).
3. Copies `tasks.db` to `tasks.db.pre-v2.bak` next to the original. If the copy fails — the script aborts before opening a transaction.

---

## Rolling back

If you decide to go back to v1.x, restore the auto-created backup:

```bash
./commands/devboard-stop.sh
python scripts/migrate_v2_departments.py --rollback
./commands/devboard-start.sh
```

`--rollback` copies `tasks.db.pre-v2.bak` back over `tasks.db`. Your v1.x kanban is restored bit-for-bit. The `departments` table and the new columns are gone after rollback.

---

## Backward compatibility for clients

v2.0 keeps every v1.x REST endpoint live. Old curl scripts, browser bookmarks, and homegrown integrations keep working:

| Call | v1.x behaviour | v2.0 behaviour |
|---|---|---|
| `GET /api/tasks` | Returns all tasks. | Returns tasks of `dev` (the default department). |
| `GET /api/chat` | Returns the global chat. | Returns chat of `dev`. |
| `POST /api/tasks` | Creates a task. | Creates a task in `dev`. |
| `POST /api/chat` | Posts to the global chat. | Posts to `dev` chat. |

To address another department, send the header `X-Department: <id>` (e.g. `X-Department: marketing`) or use the new `?department=<id>` query parameter. The dashboard's JavaScript stores the active department in `localStorage` under `devboard:current_department` and sets the header automatically.

If you archive the `dev` department (`PATCH /api/departments/dev/archive`), the fallback stops working and legacy endpoints start returning `400` until you set `X-Department` explicitly. Until then, every v1.x integration keeps running unchanged.

---

## Verifying the migration

After upgrading, two checks confirm the state:

```bash
sqlite3 data/tasks.db "SELECT value FROM schema_meta WHERE key='version';"
# expected: v2.0-departments

sqlite3 data/tasks.db "SELECT id, name FROM departments;"
# expected: dev|Dev
```

If you want a stronger guarantee, run the snapshot smoke test against your own database. It asserts no row counts change, every task lands in `dev`, and every non-global role gets `department_id = 'dev'`:

```bash
./mcp_server/.venv/bin/pytest mcp_server/tests/test_v2_migration_smoke.py -v
```

The test replays the anonymised fixture `tests/fixtures/v1.6_snapshot.db` (built by `tests/fixtures/build_v1_6_snapshot.py`) — it does not touch your real database.

---

## What is **not** migrated

Some v2.0 surfaces are forward-only. The migration does not invent data for them — they stay empty until you use the relevant feature:

- **Other departments.** Only `dev` is created automatically. Use the HR role (Sidebar → `+ Department`) to create `Marketing`, `Design`, etc.
- **`tasks.requester_department_id` and `tasks.requester_role_slug`.** Both stay `NULL` on v1.x rows — they are intra-department by definition. New cross-department tasks fill them via `POST /api/departments/<target>/tasks`.
- **`inter_department_events`.** Created empty. It only fills when a Lead creates a cross-department task.
- **`hr_sessions`.** Created empty. It only fills when the HR pipeline runs.

---

## Troubleshooting

**The dashboard refuses to start with `migration failed, see logs`.**
Check `data/dashboard.log` for the SQLite error. The most common cause is a corrupt v1.x database (e.g. unfinished WAL). Restore from `data/backups/` and try again.

**My old tasks do not appear after the upgrade.**
Open the dashboard, look at the sidebar — you are probably looking at a freshly created department instead of `Dev`. Click `Dev` in the **Departments** section. Or run `sqlite3 data/tasks.db "SELECT department_id, count(*) FROM tasks GROUP BY department_id;"` — all your old rows should be on `dev`.

**The script says `Миграция уже выполнена` but I do not see departments in the UI.**
Clear your browser localStorage entry `devboard:current_department` and reload. The frontend caches the last-known department; if that entry is stale, it can hide the sidebar list until the next request.

**`scripts/migrate_v2_departments.py` does not exist on my checkout.**
You are on a pre-v2.0 commit. Run `git pull` and check the file appears under `scripts/`. Earlier alpha builds (`v2.0-alpha.*`) already shipped it, but only the v2.0.0 release wires it into the dashboard auto-start path.

---

## Related documents

- [ADR-003 — Departments data model](adr/0003-departments.md)
- [ADR-004 — HR role and create pipeline](adr/0004-hr-role.md)
- [ADR-005 — Inter-department workflow](adr/0005-inter-department.md)
- [ARCHITECTURE.md §8 — Departments layer](../ARCHITECTURE.md)
- Smoke test — `mcp_server/tests/test_v2_migration_smoke.py`
- Migration script — `scripts/migrate_v2_departments.py`

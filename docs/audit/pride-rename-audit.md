# Pride → Devboard Rename Audit

**Date:** 2026-05-25
**Total References:** 390
**Unique Files:** 96

## Summary by Priority

| Priority | Count | Impact |
|----------|-------|--------|
| CRITICAL | 23 | Code: module names, imports, MCP config |
| HIGH | 6 | Config: environment variables |
| MEDIUM | 359 | Docs: comments, examples, references |

## CRITICAL Priority (23 references)

| File | Line | Content |
|------|------|---------|
| `mcp_server/htmlcov/status.json` | 1 | "This file is an internal implementation detail to speed up HTML report gen... |
| `mcp_server/pride_tasks/__init__.py` | 1 | ... |
| `mcp_server/pride_tasks/__main__.py` | 1 |  `python -m pride_tasks`."""... |
| `mcp_server/pride_tasks/__main__.py` | 3 | ... |
| `mcp_server/pride_tasks/db.py` | 1 | ... |
| `mcp_server/pride_tasks/db.py` | 68 | ... |
| `mcp_server/pride_tasks/db.py` | 70 | ... |
| `mcp_server/pride_tasks/router.py` | 8 |  вызывает `python -m pride_tasks.router pick`,... |
| `mcp_server/pride_tasks/router.py` | 151 | ... |
| `mcp_server/pride_tasks/server.py` | 1 | ... |
| `mcp_server/pride_tasks/server.py` | 4 | ... |
| `mcp_server/pride_tasks/server.py` | 8 | ... |
| `mcp_server/pride_tasks/server.py` | 25 |  E402... |
| `mcp_server/pride_tasks/server.py` | 28 | ... |
| `mcp_server/pride_tasks/server.py` | 31 | ... |
| `mcp_server/pride_tasks/server.py` | 35 |  %s", DB_PATH)... |
| `mcp_server/pride_tasks/server.py` | 42 | ... |
| `mcp_server/pride_tasks/server.py` | 456 | ... |
| `mcp_server/pride_tasks/template_loader.py` | 30 | ... |
| `mcp_server/pride_tasks/tools.py` | 16 | ... |
| `mcp_server/pride_tasks/tools.py` | 17 | ... |
| `mcp_server/pride_tasks/tools.py` | 432 | ... |
| `setup.py` | 127 |  ["-m", "pride_tasks"],... |

## HIGH Priority (6 references)

| File | Line | Variable |
|------|------|----------|
| `CHANGELOG.md` | 85 | `PRIDE_DASHBOARD_PORT` |
| `README_WINDOWS.md` | 94 | `PRIDE_DASHBOARD_PORT` |
| `commands/devboard-start.sh` | 50 | `PRIDE_DASHBOARD_HOST` |
| `commands/devboard-start.sh` | 52 | `PRIDE_TASKS_DB` |
| `docs/INSTALL_TROUBLESHOOTING.md` | 103 | `PRIDE_DASHBOARD_PORT` |
| `docs/manual-test-checklist-phase-1.6.md` | 72 | `PRIDE_TEAM_MODEL` |

## MEDIUM Priority (359 references)

_No functional impact—documentation, comments, examples only._

| File | Line Count |
|------|------------|
| `AGENTS.md` | 6 |
| `ARCHITECTURE.md` | 13 |
| `DEPLOYMENT.md` | 6 |
| `README.md` | 8 |
| `README.ru.md` | 7 |
| `approval_gates.md` | 1 |
| `commands/devboard-managing.sh` | 5 |
| `commands/devboard-start.sh` | 4 |
| `commands/devboard-work.sh` | 5 |
| `dashboard/app.py` | 26 |
| `dashboard/hr.py` | 8 |
| `dashboard/static/app.js` | 1 |
| `dashboard/tests/test_api.py` | 1 |
| `dashboard/tests/test_api_manager_bootstrap.py` | 2 |
| `dashboard/tests/test_assignee_fix.py` | 1 |
| `dashboard/tests/test_hr_pipeline.py` | 10 |
| `dashboard/tests/test_inherits_skills.py` | 2 |
| `dashboard/tests/test_phase15_e2e.py` | 2 |
| `dashboard/tests/test_phase1_adr009.py` | 10 |
| `dashboard/tests/test_phase2_marketing.py` | 1 |
| `dashboard/tests/test_stats_endpoint.py` | 4 |
| `dashboard/tests/test_team_api.py` | 3 |
| `dashboard/tests/test_team_process.py` | 30 |
| `dashboard/tests/test_v2_e2e.py` | 1 |
| `docs/AGENTS_EXTENDED.md` | 6 |
| `docs/INSTALL_TROUBLESHOOTING.md` | 1 |
| `docs/adr/0001-llm-provider.md` | 4 |
| `docs/adr/0002-role-format.md` | 5 |
| `docs/adr/0005-inter-department.md` | 2 |
| `docs/adr/0006-token-optimization.md` | 2 |
| `docs/adr/0007-memory-layer.md` | 3 |
| `docs/adr/0008-channels.md` | 3 |
| `docs/adr/0009-managing-director.md` | 3 |
| `docs/audit/pride-rename-audit.md` | 38 |
| `docs/i18n-audit.md` | 1 |
| `docs/launch/devto-post.md` | 2 |
| `docs/launch/showhn-comment.md` | 1 |
| `docs/manual-test-checklist-phase-1.6.md` | 1 |
| `docs/migration-v2.md` | 1 |
| `docs/qa/coverage-audit.md` | 11 |
| `docs/qa/token-opt-audit-2026-05.md` | 4 |
| `mcp.json` | 3 |
| `mcp_server/tests/conftest.py` | 3 |
| `mcp_server/tests/test_alerts.py` | 2 |
| `mcp_server/tests/test_artifacts.py` | 1 |
| `mcp_server/tests/test_atomic.py` | 1 |
| `mcp_server/tests/test_db.py` | 1 |
| `mcp_server/tests/test_departments_db.py` | 2 |
| `mcp_server/tests/test_manager_memory.py` | 1 |
| `mcp_server/tests/test_migrate_тимлид_to_dev_lead.py` | 1 |
| `mcp_server/tests/test_phase1_adr009_migration.py` | 2 |
| `mcp_server/tests/test_planning_session.py` | 1 |
| `mcp_server/tests/test_router.py` | 4 |
| `mcp_server/tests/test_s15_token_opt.py` | 1 |
| `mcp_server/tests/test_tools.py` | 5 |
| `mcp_server/tests/test_tools_departments.py` | 1 |
| `mcp_server/tests/test_tools_errors.py` | 3 |
| `mcp_server/tests/test_v2_migration_smoke.py` | 2 |
| `roles/dev/lead.md` | 7 |
| `roles/devops.md` | 2 |
| `roles/examples/code-reviewer.md` | 3 |
| `roles/examples/data-analyst.md` | 4 |
| `roles/examples/designer.md` | 3 |
| `roles/examples/pm.md` | 7 |
| `roles/examples/security-auditor.md` | 4 |
| `roles/frontend.md` | 1 |
| `roles/hr.md` | 3 |
| `roles/marketing/lead.md` | 1 |
| `roles/qa.md` | 1 |
| `roles/архитектор.md` | 1 |
| `roles/бэкенд.md` | 3 |
| `roles/техписатель.md` | 1 |
| `roles/управляющий.md` | 1 |
| `scripts/migrate_phase1_adr009.py` | 5 |
| `scripts/migrate_s15_model_hint.py` | 3 |
| `scripts/migrate_v2_departments.py` | 3 |
| `scripts/migrate_тимлид_to_dev_lead.py` | 3 |
| `scripts/stress_test.py` | 8 |
| `tests/fixtures/build_v1_6_snapshot.py` | 2 |
| `tests/test_company_context.py` | 1 |
| `tests/test_model_hint.py` | 2 |
| `tests/test_model_hint_routing.py` | 1 |
| `tests/test_phase16.py` | 5 |
| `tests/test_task_parser.py` | 1 |
| `ПЕРЕДАЧА_СЕССИИ.md` | 4 |

## Implementation Plan

### Phase 1: CRITICAL (Code Changes)

```bash
# Rename directory
git mv mcp_server/pride_tasks mcp_server/devboard_tasks

# Replace imports: pride_tasks -> devboard_tasks
find . -type f \( -name '*.py' -o -name '*.sh' \) \
  ! -path './.git/*' ! -path './.venv/*' \
  -exec sed -i 's/pride_tasks/devboard_tasks/g' {} +

# Replace tool name: pride-tasks -> devboard-tasks
find . -type f \( -name '*.json' -o -name '*.py' \) \
  ! -path './.git/*' ! -path './.venv/*' \
  -exec sed -i 's/pride-tasks/devboard-tasks/g' {} +
```

### Phase 2: HIGH (Environment Variables)

```bash
# Replace all PRIDE_* env vars with DEVBOARD_*
find . -type f \( -name '*.py' -o -name '*.sh' -o -name '*.json' \) \
  ! -path './.git/*' ! -path './.venv/*' \
  -exec sed -i \
    -e 's/PRIDE_TASKS_DB/DEVBOARD_TASKS_DB/g' \
    -e 's/PRIDE_DASHBOARD_PORT/DEVBOARD_DASHBOARD_PORT/g' \
    -e 's/PRIDE_DASHBOARD_HOST/DEVBOARD_DASHBOARD_HOST/g' \
    -e 's/PRIDE_DASHBOARD_LOG_LEVEL/DEVBOARD_DASHBOARD_LOG_LEVEL/g' \
    -e 's/PRIDE_HR_CLAUDE_CMD/DEVBOARD_HR_CLAUDE_CMD/g' \
    -e 's/PRIDE_MCP_CONFIG/DEVBOARD_MCP_CONFIG/g' \
    -e 's/PRIDE_TEAM_MODEL/DEVBOARD_TEAM_MODEL/g' \
  {} +
```

### Phase 3: MEDIUM (Documentation)

Manually update markdown files and comments for consistency.

## Verification

After all phases complete, verify with:

```bash
grep -r 'pride_tasks\|pride-tasks\|PRIDE_' . \
  --include='*.py' --include='*.sh' --include='*.json' \
  --include='*.md' 2>/dev/null | grep -v '.git' | wc -l
```

Result should be **0**.
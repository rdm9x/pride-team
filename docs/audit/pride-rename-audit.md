# Pride → Devboard Rename Audit

**Date:** 2026-05-25
**Total References Found:** 29
**Files Affected:** 26

## Summary by Priority

| Priority | Count | Category |
|----------|-------|----------|
| CRITICAL | 2 | Code changes (module, imports, MCP config) |
| HIGH | 8 | Configuration (env vars) |
| MEDIUM | 19 | Documentation (comments, examples) |

## CRITICAL Priority

__2 references__

| File | Type | Current | New | Line |
|------|------|---------|-----|------|
| `mcp_server/pride_tasks/__main__.py` | module | `pride_tasks` | `devboard_tasks` | 1 |
| `mcp_server/pride_tasks/router.py` | module | `pride_tasks` | `devboard_tasks` | 8 |

## HIGH Priority

__8 references__

| File | Type | Current | New | Line |
|------|------|---------|-----|------|
| `CHANGELOG.md` | env-var | `PRIDE_DASHBOARD_PORT` | `DEVBOARD_DASHBOARD_PORT` | 85 |
| `README_WINDOWS.md` | env-var | `PRIDE_DASHBOARD_PORT` | `DEVBOARD_DASHBOARD_PORT` | 94 |
| `commands/devboard-start.sh` | env-var | `PRIDE_DASHBOARD_HOST` | `DEVBOARD_DASHBOARD_HOST` | 50, +1 more |
| `dashboard/hr.py` | env-var | `PRIDE_MCP_CONFIG` | `DEVBOARD_MCP_CONFIG` | 181 |
| `docs/INSTALL_TROUBLESHOOTING.md` | env-var | `PRIDE_DASHBOARD_PORT` | `DEVBOARD_DASHBOARD_PORT` | 103 |
| `docs/manual-test-checklist-phase-1.6.md` | env-var | `PRIDE_TEAM_MODEL` | `DEVBOARD_TEAM_MODEL` | 72 |
| `scripts/migrate_phase1_adr009.py` | env-var | `PRIDE_TASKS_DB` | `DEVBOARD_TASKS_DB` | 143 |

## MEDIUM Priority

__19 references__

| File | Type | Current | New | Line |
|------|------|---------|-----|------|
| `ARCHITECTURE.md` | ref-string | `pride_tasks` | `devboard_tasks` | 287 |
| `dashboard/tests/test_hr_pipeline.py` | ref-string | `pride-tasks` | `devboard-tasks` | 687 |
| `dashboard/tests/test_team_process.py` | ref-string | `pride-tasks` | `devboard-tasks` | 453 |
| `docs/INSTALL_TROUBLESHOOTING.md` | ref-string | `pride_tasks` | `devboard_tasks` | 113 |
| `docs/adr/0001-llm-provider.md` | ref-string | `pride_tasks` | `devboard_tasks` | 203 |
| `docs/adr/0002-role-format.md` | ref-string | `pride-tasks` | `devboard-tasks` | 250 |
| `docs/adr/0005-inter-department.md` | ref-string | `pride-tasks` | `devboard-tasks` | 508 |
| `docs/audit/pride-rename-audit.md` | ref-string | `pride-tasks` | `devboard-tasks` | 80 |
| `docs/launch/devto-post.md` | ref-string | `pride_tasks` | `devboard_tasks` | 89 |
| `docs/launch/showhn-comment.md` | ref-string | `pride-tasks` | `devboard-tasks` | 39 |
| `docs/manual-test-checklist-phase-1.6.md` | ref-string | `pride-tasks` | `devboard-tasks` | 20 |
| `docs/qa/token-opt-audit-2026-05.md` | ref-string | `pride_tasks` | `devboard_tasks` | 45 |
| `mcp.json` | ref-string | `pride_tasks` | `devboard_tasks` | 6 |
| `mcp_server/htmlcov/status.json` | ref-string | `pride_tasks` | `devboard_tasks` | 1 |
| `roles/dev/lead.md` | ref-string | `pride_tasks` | `devboard_tasks` | 247 |
| `scripts/stress_test.py` | ref-string | `pride-tasks` | `devboard-tasks` | 1 |
| `setup.py` | ref-string | `pride_tasks` | `devboard_tasks` | 127 |
| `tests/fixtures/build_v1_6_snapshot.py` | ref-string | `pride_tasks` | `devboard_tasks` | 28 |
| `ПЕРЕДАЧА_СЕССИИ.md` | ref-string | `pride_tasks` | `devboard_tasks` | 161 |

## Implementation Strategy

### Phase 1: CRITICAL (Execute First)

1. **Rename module directory:**
   ```bash
   git mv mcp_server/pride_tasks mcp_server/devboard_tasks
   ```

2. **Update all imports** (`from pride_tasks` → `from devboard_tasks`)
   - Run find+replace in entire codebase
   - Files: `dashboard/`, `mcp_server/`, `tests/`, `scripts/`

3. **Update MCP configuration:**
   - `.mcp.json`: tool name
   - `setup.py`: entry point

### Phase 2: HIGH (Configuration)

Rename environment variables in all occurrences:
```
PRIDE_TASKS_DB → DEVBOARD_TASKS_DB
PRIDE_DASHBOARD_PORT → DEVBOARD_DASHBOARD_PORT
PRIDE_DASHBOARD_HOST → DEVBOARD_DASHBOARD_HOST
PRIDE_DASHBOARD_LOG_LEVEL → DEVBOARD_DASHBOARD_LOG_LEVEL
PRIDE_HR_CLAUDE_CMD → DEVBOARD_HR_CLAUDE_CMD
PRIDE_MCP_CONFIG → DEVBOARD_MCP_CONFIG
PRIDE_TEAM_MODEL → DEVBOARD_TEAM_MODEL
```

### Phase 3: MEDIUM (Documentation)

Update markdown files and comments—no functional impact, but improves consistency.

## Verification

After completing all phases, run:

```bash
grep -r 'pride_tasks\|pride-tasks\|PRIDE_' . \
  --include='*.py' --include='*.sh' --include='*.json' \
  --include='*.md' 2>/dev/null | grep -v '.git' | wc -l
```

Expected result: **0** (or only whitelisted legacy references)
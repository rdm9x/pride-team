# Performance Baseline — pride-team v1.0

## Test Environment

| Parameter | Value |
|---|---|
| Date | 2026-05-22 |
| OS | macOS Darwin 25.5.0 (arm64) |
| CPU | Apple M3 |
| RAM | 8 GB |
| Python | 3.13.11 |
| SQLite | 3.51.0 |
| Dataset | 1000 tasks (200 epics × 5) + 5000 chat messages |
| DB size | 1.33 MB |
| Script | `scripts/stress_test.py` (E8.5) |

## Results

| Endpoint | p50 (ms) | p95 (ms) | p99 (ms) | mean (ms) | max (ms) | SLA | Status |
|---|---|---|---|---|---|---|---|
| list_tasks(50) | 0.70 | 0.75 | 0.80 | 0.70 | 0.85 | <200ms | ✅ PASS |
| get_task(id) | 0.61 | 0.68 | 0.74 | 0.62 | 1.38 | <100ms | ✅ PASS |
| chat_recent(50) | 0.34 | 0.40 | 0.41 | 0.35 | 0.42 | <100ms | ✅ PASS |

### Additional (no SLA, context only)

| Endpoint | p50 (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| chat_post + chat_recent (combined write+read) | 1.04 | 1.29 | 1.36 |

## Notes

All three hot paths are **well within SLA** — p95 latency is 100–300× below the limit on Apple M3 / SQLite 3.51 with WAL mode.

**Why so fast:**
- SQLite WAL mode (`PRAGMA journal_mode = WAL`) allows concurrent reads without blocking.
- All three read operations (`list_tasks`, `get_task`, `chat_recent`) open a new connection per call but SQLite is in-process, so there is no network or IPC overhead.
- Existing indexes cover all query patterns: `idx_tasks_status`, `idx_tasks_assignee`, `idx_tasks_parent`, `idx_chat_created`.
- Dataset (1.33 MB) fits entirely in the OS page cache after warmup.

**Potential bottleneck — `insert_task` serialization:**
Every write acquires a per-file `fcntl.LOCK_EX` + `BEGIN IMMEDIATE`. Under the stress-seed workload, 1000 inserts took 0.63 s (~1591 task/s). This is acceptable for the current single-server deployment but would become a bottleneck under concurrent multi-agent writes at >500 tasks/s sustained throughput.

**`get_task` max outlier (1.38 ms):**
A single call spiked to 1.38 ms (≈2× mean). This is consistent with OS scheduler preemption on the first post-warmup call and is not a structural issue.

## Recommendations

1. **No immediate action required.** All SLA targets are met with large safety margins (p95 headroom: ×266 for list_tasks, ×147 for get_task, ×251 for chat_recent).

2. **Monitor at scale.** If the task count grows beyond ~50 000 rows, add a composite index on `(status, created_at)` to speed up `list_tasks` with status-filter, since the current query uses `ORDER BY created_at DESC LIMIT ?` without a covering index.

3. **Write concurrency.** If multiple agents write simultaneously (>10 concurrent writers), replace the per-connection `write_lock` with a WAL-only approach or migrate to SQLite with `BEGIN CONCURRENT` (SQLite 3.39+) to reduce lock contention.

4. **Deprecation warning.** `sqlite3.version` is deprecated in Python 3.13 and will be removed in 3.14. The stress script uses it only for diagnostics; switch to `sqlite3.sqlite_version` only.

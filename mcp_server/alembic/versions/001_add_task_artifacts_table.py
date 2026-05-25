"""Миграция: добавить таблицу task_artifacts.

revision: 001
create_date: 2026-05-25

Создаёт таблицу task_artifacts с FK на tasks.id и индексом на task_id.
"""

def upgrade():
    """Создать таблицу task_artifacts."""
    upgrade_sql = """
    CREATE TABLE IF NOT EXISTS task_artifacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT NOT NULL,
        file_path TEXT NOT NULL,
        kind TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        FOREIGN KEY (task_id) REFERENCES tasks(id),
        CONSTRAINT unique_artifact UNIQUE (task_id, file_path)
    );

    CREATE INDEX IF NOT EXISTS idx_artifacts_task ON task_artifacts(task_id);
    CREATE INDEX IF NOT EXISTS idx_artifacts_created ON task_artifacts(created_at);
    """
    return upgrade_sql


def downgrade():
    """Удалить таблицу task_artifacts."""
    downgrade_sql = """
    DROP INDEX IF EXISTS idx_artifacts_created;
    DROP INDEX IF EXISTS idx_artifacts_task;
    DROP TABLE IF EXISTS task_artifacts;
    """
    return downgrade_sql

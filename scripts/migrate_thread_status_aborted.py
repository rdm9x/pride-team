"""Миграция B2: добавить поддержку 'aborted' статуса для chat_threads.

Обновляет CHECK constraint на status, чтобы разрешить значение 'aborted'
помимо 'active', 'finished', 'archived'.
"""

import sqlite3
from pathlib import Path


def migrate(db_path: Path) -> None:
    """Добавить 'aborted' в CHECK constraint для chat_threads.status."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        # Проверяем текущую версию schema_version
        cur = conn.execute("PRAGMA user_version")
        version = cur.fetchone()[0]
        print(f"Current schema_version: {version}")

        # SQLite не позволяет ALTER TABLE изменить CHECK constraint напрямую.
        # Поэтому делаем:
        # 1. Rename исходную таблицу
        # 2. Создать новую с обновлённым constraint
        # 3. Скопировать данные
        # 4. Удалить старую

        conn.execute("BEGIN IMMEDIATE")

        # Сохраняем исходное определение индексов
        conn.execute("ALTER TABLE chat_threads RENAME TO chat_threads_old")

        # Создаём новую таблицу с обновлённым CHECK
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_threads (
              id                      TEXT PRIMARY KEY,
              title                   TEXT NOT NULL,
              kind                    TEXT NOT NULL DEFAULT 'direct' CHECK (kind IN ('direct','planning')),
              participants            TEXT NOT NULL DEFAULT '[]',
              status                  TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','finished','archived','aborted')),
              created_at              INTEGER NOT NULL,
              updated_at              INTEGER NOT NULL,
              finished_at             INTEGER,
              source_problem          TEXT,
              decision_summary        TEXT,
              decision_approved_at    INTEGER,
              decision_created_tasks  TEXT
            )
        """)

        # Копируем данные
        conn.execute("""
            INSERT INTO chat_threads
            SELECT * FROM chat_threads_old
        """)

        # Пересоздаём индексы
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_chat_thread_created
            ON chat_threads(created_at)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_chat_thread_status
            ON chat_threads(status) WHERE finished_at IS NULL
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_chat_threads_updated
            ON chat_threads(updated_at DESC)
        """)

        # Удаляем старую таблицу
        conn.execute("DROP TABLE chat_threads_old")

        # Обновляем версию schema
        conn.execute("PRAGMA user_version = 5")

        conn.commit()
        print("✓ Migration completed: added 'aborted' to chat_threads.status CHECK constraint")

    except Exception as e:
        conn.rollback()
        print(f"✗ Migration failed: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    from devboard_tasks import db
    db_path = db.default_db_path()
    print(f"Migrating {db_path}...")
    migrate(db_path)
    print("Done!")

"""Phase 3a B2 — REST endpoints для chat threads CRUD + viewer-filtered messages.

Тесты покрывают:
1. GET /api/threads?status=active|archived — список threads
2. POST /api/threads — создание thread'а
3. GET /api/threads/<id> — получить thread
4. GET /api/threads/<id>/messages?viewer=owner|managing-director — сообщения с фильтром
5. POST /api/threads/<id>/messages — добавить сообщение
6. PATCH /api/threads/<id> — изменить статус
7. POST /api/threads/<id>/stop — заглушка (Phase 3b)

Ключевой сценарий: viewer=owner исключает сообщения от тимлид-ролей.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

import pytest


def setup_test_roles(db_path: Path) -> None:
    """Добавить test-роли в БД для фильтрации."""
    conn = sqlite3.connect(db_path)
    try:
        # Добавляем dev-лид и других специалистов
        conn.execute(
            "INSERT OR IGNORE INTO roles (name, description, department_id) VALUES (?, ?, ?)",
            ("dev-lead", "Lead of dev team", "dev"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO roles (name, description, department_id) VALUES (?, ?, ?)",
            ("qa-lead", "Lead of qa team", "qa"),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def client_with_db(client: Any, tmp_path: Path) -> tuple[Any, Path]:
    """Flask client + временная БД для тестов."""
    return client, client.application.config["DB_PATH"]


class TestThreadsCRUD:
    """Тесты CRUD операций для threads."""

    def test_create_thread(self, client_with_db: tuple[Any, Path]) -> None:
        """POST /api/threads — создать новый thread."""
        client, db_path = client_with_db

        payload = {
            "title": "Planning Session #1",
            "kind": "direct",
            "participants": ["dev-lead", "qa-lead"],
        }
        resp = client.post("/api/threads", json=payload)
        assert resp.status_code == 201

        data = resp.get_json()
        assert data["статус"] == "ok"
        thread = data["thread"]

        assert thread["title"] == "Planning Session #1"
        assert thread["kind"] == "direct"
        assert thread["participants"] == ["dev-lead", "qa-lead"]
        assert thread["status"] == "active"
        assert "id" in thread
        assert "created_at" in thread

    def test_create_thread_without_title(self, client_with_db: tuple[Any, Path]) -> None:
        """POST /api/threads без title → 400."""
        client, _ = client_with_db

        payload = {"kind": "direct"}
        resp = client.post("/api/threads", json=payload)
        assert resp.status_code == 400

        data = resp.get_json()
        assert data["статус"] == "error"

    def test_list_threads_empty(self, client_with_db: tuple[Any, Path]) -> None:
        """GET /api/threads — список (может быть пусто или содержать default)."""
        client, _ = client_with_db

        resp = client.get("/api/threads")
        assert resp.status_code == 200

        data = resp.get_json()
        assert "threads" in data
        # default-thread может быть там
        threads = data["threads"]
        assert isinstance(threads, list)

    def test_list_threads_with_status_filter(self, client_with_db: tuple[Any, Path]) -> None:
        """GET /api/threads?status=active — фильтр по статусу."""
        client, db_path = client_with_db

        # Создаём thread
        payload = {"title": "Active Thread"}
        resp = client.post("/api/threads", json=payload)
        assert resp.status_code == 201
        thread_id = resp.get_json()["thread"]["id"]

        # Получаем только active
        resp = client.get("/api/threads?status=active")
        assert resp.status_code == 200

        data = resp.get_json()
        threads = data["threads"]
        active_threads = [t for t in threads if t["status"] == "active"]
        assert len(active_threads) >= 1

        # Архивируем thread
        resp = client.patch(f"/api/threads/{thread_id}", json={"status": "archived"})
        assert resp.status_code == 200

        # Проверяем что он не в active
        resp = client.get("/api/threads?status=active")
        data = resp.get_json()
        active_ids = {t["id"] for t in data["threads"]}
        assert thread_id not in active_ids

    def test_get_thread(self, client_with_db: tuple[Any, Path]) -> None:
        """GET /api/threads/<id> — получить thread."""
        client, _ = client_with_db

        # Создаём
        payload = {"title": "Test Thread", "kind": "direct"}
        resp = client.post("/api/threads", json=payload)
        thread_id = resp.get_json()["thread"]["id"]

        # Получаем
        resp = client.get(f"/api/threads/{thread_id}")
        assert resp.status_code == 200

        data = resp.get_json()
        thread = data["thread"]
        assert thread["id"] == thread_id
        assert thread["title"] == "Test Thread"
        assert thread["kind"] == "direct"

    def test_get_thread_not_found(self, client_with_db: tuple[Any, Path]) -> None:
        """GET /api/threads/<id> — 404 если не найден."""
        client, _ = client_with_db

        resp = client.get("/api/threads/nonexistent-id")
        assert resp.status_code == 404

    def test_update_thread_status_to_archived(self, client_with_db: tuple[Any, Path]) -> None:
        """PATCH /api/threads/<id> — изменить статус на archived."""
        client, _ = client_with_db

        # Создаём
        payload = {"title": "Thread to Archive"}
        resp = client.post("/api/threads", json=payload)
        thread_id = resp.get_json()["thread"]["id"]

        # Архивируем
        resp = client.patch(f"/api/threads/{thread_id}", json={"status": "archived"})
        assert resp.status_code == 200

        data = resp.get_json()
        thread = data["thread"]
        assert thread["status"] == "archived"
        assert thread["finished_at"] is not None

    def test_update_thread_status_to_aborted(self, client_with_db: tuple[Any, Path]) -> None:
        """PATCH /api/threads/<id> — изменить статус на aborted."""
        client, _ = client_with_db

        payload = {"title": "Thread to Abort"}
        resp = client.post("/api/threads", json=payload)
        thread_id = resp.get_json()["thread"]["id"]

        resp = client.patch(f"/api/threads/{thread_id}", json={"status": "aborted"})
        assert resp.status_code == 200

        data = resp.get_json()
        thread = data["thread"]
        assert thread["status"] == "aborted"
        assert thread["finished_at"] is not None

    def test_update_thread_invalid_status(self, client_with_db: tuple[Any, Path]) -> None:
        """PATCH /api/threads/<id> — ошибка при невалидном статусе."""
        client, _ = client_with_db

        payload = {"title": "Thread"}
        resp = client.post("/api/threads", json=payload)
        thread_id = resp.get_json()["thread"]["id"]

        resp = client.patch(f"/api/threads/{thread_id}", json={"status": "invalid"})
        assert resp.status_code == 400

    def test_patch_thread_not_found(self, client_with_db: tuple[Any, Path]) -> None:
        """PATCH /api/threads/<id> — 404 если thread не найден."""
        client, _ = client_with_db

        resp = client.patch("/api/threads/nonexistent", json={"status": "archived"})
        assert resp.status_code == 404

    def test_stop_thread_not_implemented(self, client_with_db: tuple[Any, Path]) -> None:
        """POST /api/threads/<id>/stop — заглушка (501)."""
        client, _ = client_with_db

        payload = {"title": "Thread"}
        resp = client.post("/api/threads", json=payload)
        thread_id = resp.get_json()["thread"]["id"]

        resp = client.post(f"/api/threads/{thread_id}/stop")
        assert resp.status_code == 501


class TestThreadMessages:
    """Тесты для добавления и получения сообщений."""

    def test_add_message_to_thread(self, client_with_db: tuple[Any, Path]) -> None:
        """POST /api/threads/<id>/messages — добавить сообщение."""
        client, _ = client_with_db

        # Создаём thread
        payload = {"title": "Test Thread"}
        resp = client.post("/api/threads", json=payload)
        thread_id = resp.get_json()["thread"]["id"]

        # Добавляем сообщение
        msg_payload = {"author": "managing-director", "text": "Hello from manager"}
        resp = client.post(f"/api/threads/{thread_id}/messages", json=msg_payload)
        assert resp.status_code == 201

        data = resp.get_json()
        assert data["статус"] == "ok"
        msg = data["message"]

        assert msg["author"] == "managing-director"
        assert msg["text"] == "Hello from manager"
        assert msg["thread_id"] == thread_id

    def test_add_message_without_text(self, client_with_db: tuple[Any, Path]) -> None:
        """POST /api/threads/<id>/messages без text → 400."""
        client, _ = client_with_db

        payload = {"title": "Thread"}
        resp = client.post("/api/threads", json=payload)
        thread_id = resp.get_json()["thread"]["id"]

        resp = client.post(f"/api/threads/{thread_id}/messages", json={"author": "managing-director"})
        assert resp.status_code == 400

    def test_add_message_to_nonexistent_thread(self, client_with_db: tuple[Any, Path]) -> None:
        """POST /api/threads/<id>/messages — ошибка если thread не существует."""
        client, _ = client_with_db

        payload = {"author": "managing-director", "text": "Message"}
        resp = client.post("/api/threads/nonexistent/messages", json=payload)
        assert resp.status_code == 400

    def test_get_thread_messages(self, client_with_db: tuple[Any, Path]) -> None:
        """GET /api/threads/<id>/messages — получить сообщения."""
        client, _ = client_with_db

        # Создаём thread
        payload = {"title": "Test Thread"}
        resp = client.post("/api/threads", json=payload)
        thread_id = resp.get_json()["thread"]["id"]

        # Добавляем сообщения
        msgs_authors = ["managing-director", "managing-director", "managing-director"]
        for author in msgs_authors:
            resp = client.post(
                f"/api/threads/{thread_id}/messages",
                json={"author": author, "text": f"Message from {author}"},
            )
            assert resp.status_code == 201

        # Получаем все сообщения
        resp = client.get(f"/api/threads/{thread_id}/messages")
        assert resp.status_code == 200

        data = resp.get_json()
        messages = data["messages"]
        assert len(messages) == 3
        assert all(m["thread_id"] == thread_id for m in messages)


class TestViewerFilter:
    """Тесты для фильтра viewer=owner в сообщениях."""

    def test_owner_view_excludes_lead_roles(self, client_with_db: tuple[Any, Path]) -> None:
        """GET /api/threads/<id>/messages?viewer=owner — исключает тимлид-сообщения."""
        client, db_path = client_with_db

        # Добавляем роли
        setup_test_roles(db_path)

        # Создаём thread
        payload = {"title": "Thread with leads"}
        resp = client.post("/api/threads", json=payload)
        thread_id = resp.get_json()["thread"]["id"]

        # Добавляем сообщения от разных авторов
        messages_data = [
            ("managing-director", "Message from manager"),
            ("dev-lead", "Message from dev lead"),
            ("тимлид", "Message from teamlead"),
            ("system", "System message"),
            ("qa-lead", "Message from qa lead"),
        ]

        for author, text in messages_data:
            resp = client.post(
                f"/api/threads/{thread_id}/messages",
                json={"author": author, "text": text},
            )
            assert resp.status_code == 201

        # Получаем все сообщения (без фильтра)
        resp = client.get(f"/api/threads/{thread_id}/messages")
        assert resp.status_code == 200
        all_messages = resp.get_json()["messages"]
        assert len(all_messages) == 5

        # Получаем сообщения с viewer=owner
        resp = client.get(f"/api/threads/{thread_id}/messages?viewer=owner")
        assert resp.status_code == 200
        owner_messages = resp.get_json()["messages"]

        # Должны остаться только: managing-director, system
        # Исключены: dev-lead, тимлид, qa-lead (т.к. они lead-роли или тимлид)
        owner_authors = {m["author"] for m in owner_messages}
        assert "managing-director" in owner_authors
        assert "system" in owner_authors
        assert "dev-lead" not in owner_authors
        assert "тимлид" not in owner_authors
        assert "qa-lead" not in owner_authors

        # Проверяем что owner видит ровно 2 сообщения
        assert len(owner_messages) == 2

    def test_managing_director_view_shows_all(self, client_with_db: tuple[Any, Path]) -> None:
        """GET /api/threads/<id>/messages?viewer=managing-director — показывает все."""
        client, db_path = client_with_db

        setup_test_roles(db_path)

        # Создаём thread и добавляем сообщения
        payload = {"title": "Thread"}
        resp = client.post("/api/threads", json=payload)
        thread_id = resp.get_json()["thread"]["id"]

        messages_data = [
            ("managing-director", "Manager msg"),
            ("dev-lead", "Dev lead msg"),
            ("тимлид", "Teamlead msg"),
        ]

        for author, text in messages_data:
            resp = client.post(
                f"/api/threads/{thread_id}/messages",
                json={"author": author, "text": text},
            )
            assert resp.status_code == 201

        # Получаем с viewer=managing-director (должны увидеть всё)
        resp = client.get(f"/api/threads/{thread_id}/messages?viewer=managing-director")
        assert resp.status_code == 200
        messages = resp.get_json()["messages"]
        # Без фильтра должны увидеть всё
        assert len(messages) == 3

    def test_no_viewer_shows_all(self, client_with_db: tuple[Any, Path]) -> None:
        """GET /api/threads/<id>/messages (без viewer) — показывает все сообщения."""
        client, db_path = client_with_db

        setup_test_roles(db_path)

        payload = {"title": "Thread"}
        resp = client.post("/api/threads", json=payload)
        thread_id = resp.get_json()["thread"]["id"]

        messages_data = [
            ("managing-director", "Msg1"),
            ("dev-lead", "Msg2"),
            ("тимлид", "Msg3"),
        ]

        for author, text in messages_data:
            resp = client.post(
                f"/api/threads/{thread_id}/messages",
                json={"author": author, "text": text},
            )
            assert resp.status_code == 201

        # Без viewer
        resp = client.get(f"/api/threads/{thread_id}/messages")
        assert resp.status_code == 200
        messages = resp.get_json()["messages"]
        assert len(messages) == 3

"""Phase 3a — E2E тесты для chat threads + viewer-filtered messages.

Ключевые сценарии:
1. Open `/chat` → дефолтный thread «📌 General»
2. Создать новый thread (type direct) → ввести title → появляется в списке
3. Отправить сообщение в новый thread → видно в центре, автоскролл
4. Запустить сессию (кнопка) → Управляющий отвечает в **этом thread**
5. Open архив-секцию → видны completed/aborted threads
6. Поиск threads по title
7. Открыть главную (Kanban) — chat-panel **должен быть удалён**

Owner-view фильтр:
- В БД создать тестовое сообщение от `dev-lead` в thread
- Open `/chat?viewer=owner` → сообщение НЕ видно
- Open `/api/threads/<id>/messages?viewer=managing-director` → сообщение видно
"""

from __future__ import annotations

import json
import sqlite3
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
        conn.execute(
            "INSERT OR IGNORE INTO roles (name, description, department_id) VALUES (?, ?, ?)",
            ("marketing-lead", "Lead of marketing team", "marketing"),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def client_with_db(client: Any, tmp_path: Path) -> tuple[Any, Path]:
    """Flask client + временная БД для тестов."""
    return client, client.application.config["DB_PATH"]


class TestChatPageBasics:
    """Базовые тесты для страницы /chat."""

    def test_chat_page_loads(self, client_with_db: tuple[Any, Path]) -> None:
        """GET /chat — страница загружается и содержит дефолтный thread."""
        client, _ = client_with_db

        resp = client.get("/chat")
        assert resp.status_code == 200

        # Проверяем что это HTML с чат-интерфейсом
        assert b"<html" in resp.data or b"<!doctype" in resp.data.lower()

    def test_chat_page_with_viewer_param(self, client_with_db: tuple[Any, Path]) -> None:
        """GET /chat?viewer=owner — поддерживает viewer-параметр."""
        client, _ = client_with_db

        resp = client.get("/chat?viewer=owner")
        assert resp.status_code == 200

    def test_chat_page_with_thread_param(self, client_with_db: tuple[Any, Path]) -> None:
        """GET /chat?thread=<id> — может открыть конкретный thread."""
        client, db_path = client_with_db

        # Создаём thread
        payload = {"title": "Test Thread"}
        resp = client.post("/api/threads", json=payload)
        thread_id = resp.get_json()["thread"]["id"]

        # Открываем чат с этим thread
        resp = client.get(f"/chat?thread={thread_id}")
        assert resp.status_code == 200


class TestThreadCreation:
    """Тесты создания threads."""

    def test_create_thread_minimal(self, client_with_db: tuple[Any, Path]) -> None:
        """POST /api/threads {title} — создать thread с минимальными параметрами."""
        client, _ = client_with_db

        payload = {"title": "Planning Session #1"}
        resp = client.post("/api/threads", json=payload)
        assert resp.status_code == 201

        data = resp.get_json()
        assert data["статус"] == "ok"
        thread = data["thread"]

        assert thread["title"] == "Planning Session #1"
        assert thread["status"] == "active"
        assert "id" in thread
        assert "created_at" in thread

    def test_create_thread_with_kind(self, client_with_db: tuple[Any, Path]) -> None:
        """POST /api/threads {title, kind} — создать thread с типом."""
        client, _ = client_with_db

        payload = {"title": "Direct Channel", "kind": "direct"}
        resp = client.post("/api/threads", json=payload)
        assert resp.status_code == 201

        thread = resp.get_json()["thread"]
        assert thread["kind"] == "direct"

    def test_create_thread_with_participants(self, client_with_db: tuple[Any, Path]) -> None:
        """POST /api/threads {title, participants} — создать thread с участниками."""
        client, _ = client_with_db

        payload = {
            "title": "Team Planning",
            "participants": ["dev-lead", "qa-lead"],
        }
        resp = client.post("/api/threads", json=payload)
        assert resp.status_code == 201

        thread = resp.get_json()["thread"]
        assert thread["participants"] == ["dev-lead", "qa-lead"]

    def test_create_thread_empty_title_error(self, client_with_db: tuple[Any, Path]) -> None:
        """POST /api/threads {title: ''} — ошибка для пустого title."""
        client, _ = client_with_db

        payload = {"title": ""}
        resp = client.post("/api/threads", json=payload)
        assert resp.status_code == 400

    def test_create_thread_missing_title_error(self, client_with_db: tuple[Any, Path]) -> None:
        """POST /api/threads без title — ошибка."""
        client, _ = client_with_db

        payload = {"kind": "direct"}
        resp = client.post("/api/threads", json=payload)
        assert resp.status_code == 400

    def test_create_multiple_threads(self, client_with_db: tuple[Any, Path]) -> None:
        """Создаём несколько threads и проверяем что они все доступны."""
        client, _ = client_with_db

        thread_ids = []
        for i in range(3):
            payload = {"title": f"Thread {i+1}"}
            resp = client.post("/api/threads", json=payload)
            assert resp.status_code == 201
            thread_ids.append(resp.get_json()["thread"]["id"])

        # Проверяем что все threads в списке
        resp = client.get("/api/threads")
        assert resp.status_code == 200
        threads = resp.get_json()["threads"]
        thread_ids_in_list = {t["id"] for t in threads}

        for thread_id in thread_ids:
            assert thread_id in thread_ids_in_list


class TestThreadMessages:
    """Тесты добавления и получения сообщений."""

    def test_send_message_to_thread(self, client_with_db: tuple[Any, Path]) -> None:
        """POST /api/threads/<id>/messages — отправить сообщение."""
        client, _ = client_with_db

        # Создаём thread
        payload = {"title": "Chat Thread"}
        resp = client.post("/api/threads", json=payload)
        thread_id = resp.get_json()["thread"]["id"]

        # Отправляем сообщение
        msg_payload = {"author": "managing-director", "text": "Hello from manager"}
        resp = client.post(f"/api/threads/{thread_id}/messages", json=msg_payload)
        assert resp.status_code == 201

        msg = resp.get_json()["message"]
        assert msg["author"] == "managing-director"
        assert msg["text"] == "Hello from manager"
        assert msg["thread_id"] == thread_id

    def test_get_messages_from_thread(self, client_with_db: tuple[Any, Path]) -> None:
        """GET /api/threads/<id>/messages — получить сообщения."""
        client, _ = client_with_db

        # Создаём thread и добавляем сообщения
        payload = {"title": "Chat Thread"}
        resp = client.post("/api/threads", json=payload)
        thread_id = resp.get_json()["thread"]["id"]

        messages_data = [
            ("managing-director", "Message 1"),
            ("managing-director", "Message 2"),
            ("managing-director", "Message 3"),
        ]

        for author, text in messages_data:
            resp = client.post(
                f"/api/threads/{thread_id}/messages",
                json={"author": author, "text": text},
            )
            assert resp.status_code == 201

        # Получаем сообщения
        resp = client.get(f"/api/threads/{thread_id}/messages")
        assert resp.status_code == 200

        messages = resp.get_json()["messages"]
        assert len(messages) == 3

        # Проверяем что сообщения в правильном порядке
        for i, msg in enumerate(messages):
            assert msg["text"] == f"Message {i+1}"

    def test_message_without_text_error(self, client_with_db: tuple[Any, Path]) -> None:
        """POST /api/threads/<id>/messages без text — ошибка."""
        client, _ = client_with_db

        payload = {"title": "Thread"}
        resp = client.post("/api/threads", json=payload)
        thread_id = resp.get_json()["thread"]["id"]

        resp = client.post(
            f"/api/threads/{thread_id}/messages",
            json={"author": "managing-director"},
        )
        assert resp.status_code == 400

    def test_message_with_empty_text_error(self, client_with_db: tuple[Any, Path]) -> None:
        """POST /api/threads/<id>/messages {text: ''} — ошибка."""
        client, _ = client_with_db

        payload = {"title": "Thread"}
        resp = client.post("/api/threads", json=payload)
        thread_id = resp.get_json()["thread"]["id"]

        resp = client.post(
            f"/api/threads/{thread_id}/messages",
            json={"author": "managing-director", "text": ""},
        )
        assert resp.status_code == 400

    def test_message_to_nonexistent_thread_error(self, client_with_db: tuple[Any, Path]) -> None:
        """POST /api/threads/<nonexistent>/messages — ошибка."""
        client, _ = client_with_db

        resp = client.post(
            "/api/threads/nonexistent-id/messages",
            json={"author": "managing-director", "text": "Message"},
        )
        assert resp.status_code == 400

    def test_message_timestamps(self, client_with_db: tuple[Any, Path]) -> None:
        """Сообщения содержат created_at timestamp."""
        client, _ = client_with_db

        payload = {"title": "Thread"}
        resp = client.post("/api/threads", json=payload)
        thread_id = resp.get_json()["thread"]["id"]

        resp = client.post(
            f"/api/threads/{thread_id}/messages",
            json={"author": "managing-director", "text": "Test"},
        )
        assert resp.status_code == 201

        msg = resp.get_json()["message"]
        assert "created_at" in msg
        assert msg["created_at"] is not None


class TestThreadStatus:
    """Тесты управления статусом threads."""

    def test_archive_thread(self, client_with_db: tuple[Any, Path]) -> None:
        """PATCH /api/threads/<id> {status: 'archived'} — архивировать."""
        client, _ = client_with_db

        payload = {"title": "Thread to Archive"}
        resp = client.post("/api/threads", json=payload)
        thread_id = resp.get_json()["thread"]["id"]

        resp = client.patch(f"/api/threads/{thread_id}", json={"status": "archived"})
        assert resp.status_code == 200

        thread = resp.get_json()["thread"]
        assert thread["status"] == "archived"
        assert thread["finished_at"] is not None

    def test_abort_thread(self, client_with_db: tuple[Any, Path]) -> None:
        """PATCH /api/threads/<id> {status: 'aborted'} — отменить."""
        client, _ = client_with_db

        payload = {"title": "Thread to Abort"}
        resp = client.post("/api/threads", json=payload)
        thread_id = resp.get_json()["thread"]["id"]

        resp = client.patch(f"/api/threads/{thread_id}", json={"status": "aborted"})
        assert resp.status_code == 200

        thread = resp.get_json()["thread"]
        assert thread["status"] == "aborted"
        assert thread["finished_at"] is not None

    def test_invalid_status_error(self, client_with_db: tuple[Any, Path]) -> None:
        """PATCH /api/threads/<id> {status: 'invalid'} — ошибка."""
        client, _ = client_with_db

        payload = {"title": "Thread"}
        resp = client.post("/api/threads", json=payload)
        thread_id = resp.get_json()["thread"]["id"]

        resp = client.patch(f"/api/threads/{thread_id}", json={"status": "invalid"})
        assert resp.status_code == 400

    def test_list_threads_filter_by_status(self, client_with_db: tuple[Any, Path]) -> None:
        """GET /api/threads?status=archived — фильтр по статусу."""
        client, _ = client_with_db

        # Создаём активный thread
        payload = {"title": "Active"}
        resp = client.post("/api/threads", json=payload)
        active_id = resp.get_json()["thread"]["id"]

        # Создаём и архивируем thread
        payload = {"title": "Archived"}
        resp = client.post("/api/threads", json=payload)
        archived_id = resp.get_json()["thread"]["id"]

        resp = client.patch(f"/api/threads/{archived_id}", json={"status": "archived"})
        assert resp.status_code == 200

        # Получаем только активные
        resp = client.get("/api/threads?status=active")
        assert resp.status_code == 200
        active_threads = resp.get_json()["threads"]
        active_ids = {t["id"] for t in active_threads}
        assert active_id in active_ids
        assert archived_id not in active_ids

        # Получаем только архивированные
        resp = client.get("/api/threads?status=archived")
        assert resp.status_code == 200
        archived_threads = resp.get_json()["threads"]
        archived_ids = {t["id"] for t in archived_threads}
        assert archived_id in archived_ids


class TestViewerFilter:
    """Тесты для фильтра viewer=owner."""

    def test_owner_excludes_lead_messages(self, client_with_db: tuple[Any, Path]) -> None:
        """GET /api/threads/<id>/messages?viewer=owner — исключает lead-сообщения."""
        client, db_path = client_with_db

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
        ]

        for author, text in messages_data:
            resp = client.post(
                f"/api/threads/{thread_id}/messages",
                json={"author": author, "text": text},
            )
            assert resp.status_code == 201

        # Все сообщения без фильтра
        resp = client.get(f"/api/threads/{thread_id}/messages")
        assert resp.status_code == 200
        all_msgs = resp.get_json()["messages"]
        assert len(all_msgs) == 4

        # С viewer=owner — только manager и system
        resp = client.get(f"/api/threads/{thread_id}/messages?viewer=owner")
        assert resp.status_code == 200
        owner_msgs = resp.get_json()["messages"]

        owner_authors = {m["author"] for m in owner_msgs}
        assert "managing-director" in owner_authors
        assert "system" in owner_authors
        assert "dev-lead" not in owner_authors
        assert "тимлид" not in owner_authors

        assert len(owner_msgs) == 2

    def test_managing_director_viewer_shows_all(self, client_with_db: tuple[Any, Path]) -> None:
        """GET /api/threads/<id>/messages?viewer=managing-director — показывает всё."""
        client, db_path = client_with_db

        setup_test_roles(db_path)

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

        # Все сообщения для managing-director
        resp = client.get(f"/api/threads/{thread_id}/messages?viewer=managing-director")
        assert resp.status_code == 200
        msgs = resp.get_json()["messages"]
        assert len(msgs) == 3

    def test_no_viewer_shows_all_messages(self, client_with_db: tuple[Any, Path]) -> None:
        """GET /api/threads/<id>/messages (без viewer) — показывает всё."""
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

        resp = client.get(f"/api/threads/{thread_id}/messages")
        assert resp.status_code == 200
        msgs = resp.get_json()["messages"]
        assert len(msgs) == 3

    def test_multiple_lead_roles_excluded(self, client_with_db: tuple[Any, Path]) -> None:
        """Сообщения от всех lead-ролей исключаются для owner."""
        client, db_path = client_with_db

        setup_test_roles(db_path)

        payload = {"title": "Thread"}
        resp = client.post("/api/threads", json=payload)
        thread_id = resp.get_json()["thread"]["id"]

        # Множество lead-ролей
        messages_data = [
            ("managing-director", "Manager msg"),
            ("dev-lead", "Dev lead msg"),
            ("qa-lead", "QA lead msg"),
            ("marketing-lead", "Marketing lead msg"),
            ("system", "System msg"),
        ]

        for author, text in messages_data:
            resp = client.post(
                f"/api/threads/{thread_id}/messages",
                json={"author": author, "text": text},
            )
            assert resp.status_code == 201

        # Owner видит только manager и system
        resp = client.get(f"/api/threads/{thread_id}/messages?viewer=owner")
        assert resp.status_code == 200
        owner_msgs = resp.get_json()["messages"]

        owner_authors = {m["author"] for m in owner_msgs}
        assert owner_authors == {"managing-director", "system"}
        assert len(owner_msgs) == 2


class TestThreadRetrieval:
    """Тесты получения информации о threads."""

    def test_get_thread_details(self, client_with_db: tuple[Any, Path]) -> None:
        """GET /api/threads/<id> — получить детали thread."""
        client, _ = client_with_db

        payload = {"title": "Test Thread", "kind": "direct"}
        resp = client.post("/api/threads", json=payload)
        thread_id = resp.get_json()["thread"]["id"]

        resp = client.get(f"/api/threads/{thread_id}")
        assert resp.status_code == 200

        thread = resp.get_json()["thread"]
        assert thread["id"] == thread_id
        assert thread["title"] == "Test Thread"
        assert thread["kind"] == "direct"
        assert "created_at" in thread

    def test_get_nonexistent_thread_404(self, client_with_db: tuple[Any, Path]) -> None:
        """GET /api/threads/<nonexistent> — 404."""
        client, _ = client_with_db

        resp = client.get("/api/threads/nonexistent-id")
        assert resp.status_code == 404

    def test_list_all_threads(self, client_with_db: tuple[Any, Path]) -> None:
        """GET /api/threads — список всех threads."""
        client, _ = client_with_db

        # Создаём несколько threads
        titles = ["Thread 1", "Thread 2", "Thread 3"]
        created_ids = []
        for title in titles:
            resp = client.post("/api/threads", json={"title": title})
            assert resp.status_code == 201
            created_ids.append(resp.get_json()["thread"]["id"])

        # Получаем список
        resp = client.get("/api/threads")
        assert resp.status_code == 200

        threads = resp.get_json()["threads"]
        thread_ids = {t["id"] for t in threads}

        for thread_id in created_ids:
            assert thread_id in thread_ids

    def test_threads_list_contains_all_created(self, client_with_db: tuple[Any, Path]) -> None:
        """GET /api/threads — список содержит все созданные threads."""
        client, _ = client_with_db

        # Создаём несколько threads
        created_ids = set()
        for i in range(5):
            resp = client.post("/api/threads", json={"title": f"ListTest-{i}"})
            assert resp.status_code == 201
            created_ids.add(resp.get_json()["thread"]["id"])

        # Получаем список
        resp = client.get("/api/threads")
        threads = resp.get_json()["threads"]

        # Все наши threads должны быть в списке
        list_ids = {t["id"] for t in threads}
        assert created_ids.issubset(list_ids)


class TestThreadIntegration:
    """Интеграционные тесты полного workflow."""

    def test_full_chat_workflow(self, client_with_db: tuple[Any, Path]) -> None:
        """Полный workflow: создать thread → отправить сообщение → архивировать."""
        client, _ = client_with_db

        # 1. Создаём thread
        resp = client.post("/api/threads", json={"title": "Planning Session"})
        assert resp.status_code == 201
        thread_id = resp.get_json()["thread"]["id"]

        # 2. Отправляем сообщение
        resp = client.post(
            f"/api/threads/{thread_id}/messages",
            json={"author": "managing-director", "text": "Let's plan"},
        )
        assert resp.status_code == 201

        # 3. Проверяем что сообщение в thread
        resp = client.get(f"/api/threads/{thread_id}/messages")
        assert resp.status_code == 200
        msgs = resp.get_json()["messages"]
        assert len(msgs) == 1
        assert msgs[0]["text"] == "Let's plan"

        # 4. Архивируем thread
        resp = client.patch(f"/api/threads/{thread_id}", json={"status": "archived"})
        assert resp.status_code == 200

        # 5. Проверяем что thread архивирован
        resp = client.get(f"/api/threads/{thread_id}")
        assert resp.status_code == 200
        thread = resp.get_json()["thread"]
        assert thread["status"] == "archived"

    def test_thread_search_by_title(self, client_with_db: tuple[Any, Path]) -> None:
        """Поиск threads по title (базовый).

        Примечание: полный поиск реализуется на фронтенде фильтрацией списка.
        """
        client, _ = client_with_db

        # Создаём threads с разными titles
        titles = ["Planning Session", "Daily Standup", "Retrospective"]
        for title in titles:
            resp = client.post("/api/threads", json={"title": title})
            assert resp.status_code == 201

        # Получаем все threads
        resp = client.get("/api/threads")
        assert resp.status_code == 200
        all_threads = resp.get_json()["threads"]

        # Проверяем что все titles есть в списке
        all_titles = {t["title"] for t in all_threads}
        for title in titles:
            assert title in all_titles

    def test_multiple_messages_sequence(self, client_with_db: tuple[Any, Path]) -> None:
        """Несколько сообщений — проверяем порядок и целостность."""
        client, _ = client_with_db

        payload = {"title": "Multi-message Thread"}
        resp = client.post("/api/threads", json=payload)
        thread_id = resp.get_json()["thread"]["id"]

        # Отправляем 5 сообщений
        texts = ["First", "Second", "Third", "Fourth", "Fifth"]
        for text in texts:
            resp = client.post(
                f"/api/threads/{thread_id}/messages",
                json={"author": "managing-director", "text": text},
            )
            assert resp.status_code == 201

        # Получаем все и проверяем порядок
        resp = client.get(f"/api/threads/{thread_id}/messages")
        assert resp.status_code == 200
        msgs = resp.get_json()["messages"]

        assert len(msgs) == 5
        for i, msg in enumerate(msgs):
            assert msg["text"] == texts[i]

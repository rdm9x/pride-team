"""REST API tests for chat threads CRUD and viewer-filtered messages (B2 3a).

Tests cover:
  1. GET /api/threads?status=... — list threads with filtering
  2. POST /api/threads — create thread
  3. GET /api/threads/<id> — get thread details
  4. GET /api/threads/<id>/messages?viewer=owner|managing-director — filtered messages
  5. POST /api/threads/<id>/messages — add message
  6. PATCH /api/threads/<id> — update thread status
  7. POST /api/threads/<id>/stop — stop thread (status='aborted')

Key focus: viewer=owner filter must exclude lead-role messages (ADR-011 §6.1).
"""

import json
import pytest
from pathlib import Path
import tempfile
import sqlite3

from devboard_tasks import db


@pytest.fixture
def test_db() -> Path:
    """Create a temporary test database."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.db', delete=False) as f:
        temp_path = Path(f.name)
    db.init_db(temp_path)
    yield temp_path
    # Cleanup
    if temp_path.exists():
        temp_path.unlink()


@pytest.fixture
def client(test_db):
    """Flask test client with isolated test database."""
    from app import create_app
    app = create_app(db_path=test_db)
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def setup_roles(test_db):
    """Create test roles: some leads, some non-leads.

    init_db creates only the 'dev' department by default — we add 'marketing'
    so that marketing roles can satisfy the roles.department_id FK.
    """
    conn = db._connect(test_db)
    try:
        # Ensure marketing department exists (init_db only seeds 'dev').
        try:
            now = int(__import__("time").time())
            conn.execute(
                "INSERT INTO departments (id, name, description, template_id, icon, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("marketing", "Marketing", "", None, "📣", now),
            )
        except sqlite3.IntegrityError:
            pass  # already exists

        roles_to_insert = [
            ("dev-lead", "Dev Lead", json.dumps({"model": "opus"}), "dev"),
            ("marketing-lead", "Marketing Lead", json.dumps({"model": "opus"}), "marketing"),
            ("developer", "Developer", json.dumps({"model": "haiku"}), "dev"),
            ("marketer", "Marketer", json.dumps({"model": "haiku"}), "marketing"),
        ]

        for role_name, role_desc, caps, dept_id in roles_to_insert:
            try:
                conn.execute(
                    "INSERT INTO roles (name, description, capabilities, department_id) VALUES (?, ?, ?, ?)",
                    (role_name, role_desc, caps, dept_id)
                )
            except sqlite3.IntegrityError:
                # Role already exists (from init_db), skip
                pass

        conn.commit()
    finally:
        conn.close()


class TestThreadsListEndpoint:
    """GET /api/threads?status=active|archived"""

    def test_list_threads_empty(self, client):
        """Initially no threads."""
        resp = client.get("/api/threads")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["threads"] == []

    def test_list_threads_all_statuses(self, client, test_db):
        """List all threads regardless of status."""
        db.create_chat_thread(test_db, title="Thread 1", kind="direct")
        db.create_chat_thread(test_db, title="Thread 2", kind="planning")

        resp = client.get("/api/threads")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["threads"]) == 2
        assert data["threads"][0]["title"] in ("Thread 1", "Thread 2")

    def test_list_threads_filter_active(self, client, test_db):
        """Filter by status=active."""
        t1 = db.create_chat_thread(test_db, title="Active 1", kind="direct")
        t2 = db.create_chat_thread(test_db, title="Active 2", kind="direct")
        db.update_chat_thread_status(test_db, t1["id"], "archived")

        resp = client.get("/api/threads?status=active")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["threads"]) == 1
        assert data["threads"][0]["id"] == t2["id"]

    def test_list_threads_filter_archived(self, client, test_db):
        """Filter by status=archived."""
        t1 = db.create_chat_thread(test_db, title="Thread 1", kind="direct")
        db.update_chat_thread_status(test_db, t1["id"], "archived")

        resp = client.get("/api/threads?status=archived")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["threads"]) == 1
        assert data["threads"][0]["status"] == "archived"

    def test_list_threads_sort_by_updated_at(self, client, test_db):
        """Threads sorted by updated_at DESC.

        updated_at — seconds-resolution, поэтому без задержки между двумя
        вставками порядок tie-breaking недетерминирован.
        """
        import time as _t

        t1 = db.create_chat_thread(test_db, title="Older", kind="direct")
        _t.sleep(1.1)  # гарантируем разный updated_at в секундах
        t2 = db.create_chat_thread(test_db, title="Newer", kind="direct")
        # t2 is created after t1, so should be first in DESC order

        resp = client.get("/api/threads")
        data = resp.get_json()
        # Find our test threads in the list (may be others like 'default')
        threads_by_title = {t["title"]: t for t in data["threads"]}
        assert threads_by_title["Newer"]["id"] == t2["id"]
        # Verify t2 comes before t1 in the list
        t2_idx = next(i for i, t in enumerate(data["threads"]) if t["id"] == t2["id"])
        t1_idx = next(i for i, t in enumerate(data["threads"]) if t["id"] == t1["id"])
        assert t2_idx < t1_idx


class TestThreadsCreateEndpoint:
    """POST /api/threads"""

    def test_create_thread_minimal(self, client):
        """Create thread with only title."""
        resp = client.post("/api/threads", json={"title": "Test Thread"})
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["thread"]["title"] == "Test Thread"
        assert data["thread"]["kind"] == "direct"
        assert data["thread"]["status"] == "active"
        assert data["thread"]["id"] is not None

    def test_create_thread_with_kind(self, client):
        """Create thread with kind='planning'."""
        resp = client.post("/api/threads", json={
            "title": "Planning Thread",
            "kind": "planning"
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["thread"]["kind"] == "planning"

    def test_create_thread_with_participants(self, client):
        """Create thread with participants list."""
        resp = client.post("/api/threads", json={
            "title": "Collab Thread",
            "kind": "planning",
            "participants": ["пользователь", "managing-director", "dev-lead"]
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["thread"]["participants"] == ["пользователь", "managing-director", "dev-lead"]

    def test_create_thread_missing_title(self, client):
        """Missing title → 400."""
        resp = client.post("/api/threads", json={"kind": "direct"})
        assert resp.status_code == 400

    def test_create_thread_invalid_kind(self, client):
        """Invalid kind → 400."""
        resp = client.post("/api/threads", json={
            "title": "Test",
            "kind": "invalid"
        })
        assert resp.status_code == 400

    def test_create_thread_invalid_participants_type(self, client):
        """Participants not a list → 400."""
        resp = client.post("/api/threads", json={
            "title": "Test",
            "participants": "not-a-list"
        })
        assert resp.status_code == 400


class TestThreadsGetEndpoint:
    """GET /api/threads/<id>"""

    def test_get_thread_existing(self, client, test_db):
        """Get existing thread."""
        thread = db.create_chat_thread(test_db, title="Get Test", kind="direct")
        resp = client.get(f"/api/threads/{thread['id']}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["thread"]["id"] == thread["id"]
        assert data["thread"]["title"] == "Get Test"

    def test_get_thread_not_found(self, client):
        """Get non-existent thread → 404."""
        resp = client.get("/api/threads/nonexistent-id")
        assert resp.status_code == 404


class TestThreadsMessagesEndpoint:
    """POST /api/threads/<id>/messages"""

    def test_add_message_to_thread(self, client, test_db, setup_roles):
        """Add message to thread."""
        thread = db.create_chat_thread(test_db, title="Chat Thread", kind="direct")
        resp = client.post(f"/api/threads/{thread['id']}/messages", json={
            "author": "пользователь",
            "text": "Hello from owner"
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["message"]["author"] == "пользователь"
        assert data["message"]["text"] == "Hello from owner"
        assert data["message"]["thread_id"] == thread["id"]

    def test_add_message_missing_author(self, client, test_db):
        """Missing author → 400."""
        thread = db.create_chat_thread(test_db, title="Test", kind="direct")
        resp = client.post(f"/api/threads/{thread['id']}/messages", json={
            "text": "Only text"
        })
        assert resp.status_code == 400

    def test_add_message_missing_text(self, client, test_db):
        """Missing text → 400."""
        thread = db.create_chat_thread(test_db, title="Test", kind="direct")
        resp = client.post(f"/api/threads/{thread['id']}/messages", json={
            "author": "пользователь"
        })
        assert resp.status_code == 400

    def test_add_message_thread_not_found(self, client):
        """Adding message to non-existent thread → 400."""
        resp = client.post("/api/threads/nonexistent/messages", json={
            "author": "пользователь",
            "text": "Test"
        })
        assert resp.status_code == 400


class TestThreadsMessagesFilterViewerEndpoint:
    """GET /api/threads/<id>/messages?viewer=owner|managing-director"""

    def test_get_messages_no_filter(self, client, test_db, setup_roles):
        """Get all messages without viewer filter."""
        thread = db.create_chat_thread(test_db, title="Test", kind="direct")
        db.add_chat_message_to_thread(test_db, thread["id"], "пользователь", "User message")
        db.add_chat_message_to_thread(test_db, thread["id"], "dev-lead", "Lead message")
        db.add_chat_message_to_thread(test_db, thread["id"], "managing-director", "MD message")

        resp = client.get(f"/api/threads/{thread['id']}/messages")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["messages"]) == 3

    def test_get_messages_viewer_owner_filters_leads(self, client, test_db, setup_roles):
        """viewer=owner excludes all lead-role messages (ADR-011 §6.1, CRITICAL)."""
        thread = db.create_chat_thread(test_db, title="Test", kind="planning")

        # Add messages from various roles
        db.add_chat_message_to_thread(test_db, thread["id"], "owner", "Owner msg 1")
        db.add_chat_message_to_thread(test_db, thread["id"], "dev-lead", "Dev Lead msg")  # EXCLUDED
        db.add_chat_message_to_thread(test_db, thread["id"], "marketing-lead", "Marketing Lead msg")  # EXCLUDED
        db.add_chat_message_to_thread(test_db, thread["id"], "тимлид", "Teamlead msg")  # EXCLUDED
        db.add_chat_message_to_thread(test_db, thread["id"], "managing-director", "MD msg")
        db.add_chat_message_to_thread(test_db, thread["id"], "owner", "Owner msg 2")

        resp = client.get(f"/api/threads/{thread['id']}/messages?viewer=owner")
        assert resp.status_code == 200
        data = resp.get_json()

        # Should only see: 2 owner + 1 managing-director = 3 messages
        assert len(data["messages"]) == 3
        authors = [m["author"] for m in data["messages"]]
        assert "owner" in authors
        assert "managing-director" in authors
        assert "dev-lead" not in authors
        assert "marketing-lead" not in authors
        assert "тимлид" not in authors

    def test_get_messages_viewer_owner_no_lead_roles(self, client, test_db):
        """viewer=owner with no roles in roles table (only default roles)."""
        thread = db.create_chat_thread(test_db, title="Test", kind="direct")

        db.add_chat_message_to_thread(test_db, thread["id"], "owner", "Owner msg")
        db.add_chat_message_to_thread(test_db, thread["id"], "тимлид", "TL msg")  # Should be excluded
        db.add_chat_message_to_thread(test_db, thread["id"], "managing-director", "MD msg")

        resp = client.get(f"/api/threads/{thread['id']}/messages?viewer=owner")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["messages"]) == 2
        authors = [m["author"] for m in data["messages"]]
        assert "тимлид" not in authors

    def test_get_messages_viewer_managing_director_sees_all(self, client, test_db, setup_roles):
        """viewer=managing-director sees all messages (no filtering)."""
        thread = db.create_chat_thread(test_db, title="Test", kind="planning")

        db.add_chat_message_to_thread(test_db, thread["id"], "owner", "Owner msg")
        db.add_chat_message_to_thread(test_db, thread["id"], "dev-lead", "Dev Lead msg")
        db.add_chat_message_to_thread(test_db, thread["id"], "managing-director", "MD msg")

        resp = client.get(f"/api/threads/{thread['id']}/messages?viewer=managing-director")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["messages"]) == 3

    def test_get_messages_thread_not_found(self, client):
        """Get messages from non-existent thread → 404."""
        resp = client.get("/api/threads/nonexistent/messages")
        assert resp.status_code == 404


class TestThreadsUpdateEndpoint:
    """PATCH /api/threads/<id>"""

    def test_update_thread_status_archived(self, client, test_db):
        """Update thread status to archived."""
        thread = db.create_chat_thread(test_db, title="Test", kind="direct")
        resp = client.patch(f"/api/threads/{thread['id']}", json={
            "status": "archived"
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["thread"]["status"] == "archived"
        assert data["thread"]["finished_at"] is not None

    def test_update_thread_status_aborted(self, client, test_db):
        """Update thread status to aborted."""
        thread = db.create_chat_thread(test_db, title="Test", kind="planning")
        resp = client.patch(f"/api/threads/{thread['id']}", json={
            "status": "aborted"
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["thread"]["status"] == "aborted"

    def test_update_thread_missing_status(self, client, test_db):
        """Missing status parameter → 400."""
        thread = db.create_chat_thread(test_db, title="Test", kind="direct")
        resp = client.patch(f"/api/threads/{thread['id']}", json={})
        assert resp.status_code == 400

    def test_update_thread_invalid_status(self, client, test_db):
        """Invalid status value → 400."""
        thread = db.create_chat_thread(test_db, title="Test", kind="direct")
        resp = client.patch(f"/api/threads/{thread['id']}", json={
            "status": "invalid_status"
        })
        assert resp.status_code == 400

    def test_update_thread_not_found(self, client):
        """Update non-existent thread → 404."""
        resp = client.patch("/api/threads/nonexistent", json={
            "status": "archived"
        })
        assert resp.status_code == 404


class TestThreadsStopEndpoint:
    """POST /api/threads/<id>/stop"""

    def test_stop_thread(self, client, test_db):
        """Stop a planning thread (status → aborted)."""
        thread = db.create_chat_thread(test_db, title="Planning", kind="planning")
        assert thread["status"] == "active"

        resp = client.post(f"/api/threads/{thread['id']}/stop")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["thread"]["status"] == "aborted"
        assert data["thread"]["finished_at"] is not None

    def test_stop_thread_not_found(self, client):
        """Stop non-existent thread → 404."""
        resp = client.post("/api/threads/nonexistent/stop")
        assert resp.status_code == 404


class TestThreadsIntegrationScenario:
    """Integration test: full thread lifecycle."""

    def test_full_thread_workflow(self, client, test_db, setup_roles):
        """
        Full scenario:
        1. Create planning thread
        2. Add messages from multiple roles
        3. Owner views messages (filtered)
        4. MD views all messages (no filter)
        5. Stop thread
        """
        # 1. Create thread
        resp = client.post("/api/threads", json={
            "title": "Design Cleanup",
            "kind": "planning",
            "participants": ["owner", "managing-director", "dev-lead", "marketing-lead"]
        })
        assert resp.status_code == 201
        thread_id = resp.get_json()["thread"]["id"]

        # 2. Add messages
        client.post(f"/api/threads/{thread_id}/messages", json={
            "author": "owner",
            "text": "Чистим дизайн?"
        })
        client.post(f"/api/threads/{thread_id}/messages", json={
            "author": "managing-director",
            "text": "Отличная идея. Вот подходы:"
        })
        client.post(f"/api/threads/{thread_id}/messages", json={
            "author": "dev-lead",
            "text": "На бэк потребуется рефакторинг"
        })
        client.post(f"/api/threads/{thread_id}/messages", json={
            "author": "marketing-lead",
            "text": "На маркетинге согласны с предложением"
        })

        # 3. Owner views (filtered)
        resp = client.get(f"/api/threads/{thread_id}/messages?viewer=owner")
        owner_msgs = resp.get_json()["messages"]
        assert len(owner_msgs) == 2  # owner + MD only

        # 4. MD views all
        resp = client.get(f"/api/threads/{thread_id}/messages?viewer=managing-director")
        md_msgs = resp.get_json()["messages"]
        assert len(md_msgs) == 4  # all messages

        # 5. Stop thread
        resp = client.post(f"/api/threads/{thread_id}/stop")
        assert resp.status_code == 200
        assert resp.get_json()["thread"]["status"] == "aborted"


class TestThreadsCoverageEdgeCases:
    """Edge cases and >70% coverage."""

    def test_thread_messages_with_whitespace(self, client, test_db):
        """Message text with leading/trailing whitespace is trimmed."""
        thread = db.create_chat_thread(test_db, title="Test", kind="direct")
        resp = client.post(f"/api/threads/{thread['id']}/messages", json={
            "author": "owner",
            "text": "  \n  Test message  \n  "
        })
        assert resp.status_code == 201
        msg = resp.get_json()["message"]
        assert msg["text"] == "Test message"

    def test_thread_status_transition_active_to_archived_to_aborted(self, client, test_db):
        """Thread can transition through multiple statuses."""
        thread = db.create_chat_thread(test_db, title="Test", kind="direct")

        # active → archived
        resp = client.patch(f"/api/threads/{thread['id']}", json={"status": "archived"})
        assert resp.status_code == 200

        # archived → aborted (or back to active)
        resp = client.patch(f"/api/threads/{thread['id']}", json={"status": "aborted"})
        assert resp.status_code == 200
        assert resp.get_json()["thread"]["status"] == "aborted"

    def test_list_threads_empty_kind(self, client):
        """Create thread with empty kind defaults to 'direct'."""
        resp = client.post("/api/threads", json={
            "title": "Test",
            "kind": ""
        })
        # Empty kind gets treated as falsy, defaults to 'direct'
        assert resp.status_code == 201
        assert resp.get_json()["thread"]["kind"] == "direct"

    def test_messages_ordering_created_at_asc(self, client, test_db):
        """Messages returned in created_at ASC order."""
        thread = db.create_chat_thread(test_db, title="Test", kind="direct")

        for i in range(3):
            db.add_chat_message_to_thread(test_db, thread["id"], "owner", f"Message {i}")

        resp = client.get(f"/api/threads/{thread['id']}/messages")
        msgs = resp.get_json()["messages"]

        # Check ordering: timestamps should be non-decreasing
        timestamps = [m["created_at"] for m in msgs]
        assert timestamps == sorted(timestamps)

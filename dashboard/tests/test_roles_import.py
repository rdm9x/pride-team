"""Тесты POST /api/roles/import (E7.3).

Покрытие:
1. Happy path — valid role URL → 200, файл создан.
2. Not in allowlist → 400.
3. Too large (Content-Length header) → 400.
4. Too large (streaming body, no Content-Length) → 400.
5. Invalid role format → 422.
6. Duplicate without force → 409.
7. Duplicate with force=True → 200 overwrite.
8. Path traversal attempt in name → 400 / 422.
9. Missing url field → 400.
10. gist.github.com is in allowlist → 200.
11. Import log appends on multiple imports.

Запуск из каталога `dashboard/`:
    python -m pytest tests/test_roles_import.py -v
"""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_DIR = Path(__file__).resolve().parents[1]

# roles/ нужен при импорте app.py (глобальная переменная _ROLES_DIR).
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

VALID_ROLE_CONTENT = b"""\
---
schema_version: 1
name: test-backend
description: Backend role for import tests.
llm: claude
model: claude-sonnet-4-5
temperature: 0.3
max_tokens: 8192
---
# Test backend

You are a backend developer responsible for writing
clean, well-tested Python code for the devboard project.
"""

# Role with a path-traversal-like name (should be caught by slug regex)
TRAVERSAL_ROLE_CONTENT = b"""\
---
schema_version: 1
name: ../evil
description: Role with traversal name.
llm: claude
model: claude-sonnet-4-5
---
# Evil role body content here for testing purposes
"""

# Role content that fails validator (missing required fields)
INVALID_ROLE_CONTENT = b"""\
---
name: no-schema-version
---
# body here is long enough to pass body check
"""


def _make_httpx_stream_context(
    content: bytes,
    status_code: int = 200,
    content_type: str = "text/plain",
    content_length: str | None = None,
):
    """Return a context-manager mock that mimics httpx.stream(...)."""

    # Build the mock response
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.raise_for_status = MagicMock()  # no-op (2xx assumed)

    # httpx uses lowercase header keys
    headers: dict[str, str] = {"content-type": content_type}
    if content_length is not None:
        headers["content-length"] = content_length
    mock_resp.headers = headers

    def _iter_bytes(chunk_size: int = 4096):
        offset = 0
        while offset < len(content):
            yield content[offset : offset + chunk_size]
            offset += chunk_size

    mock_resp.iter_bytes = _iter_bytes

    @contextmanager
    def _cm(*args, **kwargs):
        yield mock_resp

    return _cm


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def import_client(tmp_path: Path):
    """Flask test client with isolated DB and roles dir, patched _ROLES_DIR."""
    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    db_path = tmp_path / "test.db"

    # conftest.py already adds DASHBOARD_DIR to sys.path so `app` is importable.
    with patch("app._ROLES_DIR", roles_dir):
        from app import create_app  # type: ignore

        flask_app = create_app(db_path=db_path)
        flask_app.config["TESTING"] = True

        with flask_app.test_client() as c:
            yield c, roles_dir


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------


def test_import_happy_path(import_client):
    """Valid role from allowed host → 200, file saved, log written."""
    client, roles_dir = import_client

    stream_cm = _make_httpx_stream_context(VALID_ROLE_CONTENT, content_type="text/plain")

    with patch("httpx.stream", side_effect=stream_cm):
        resp = client.post(
            "/api/roles/import",
            json={"url": "https://raw.githubusercontent.com/org/repo/main/role.md"},
        )

    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["status"] == "ok"
    assert body["name"] == "test-backend"
    assert body["path"] == "roles/test-backend.md"
    assert body["size"] == len(VALID_ROLE_CONTENT)

    saved = roles_dir / "test-backend.md"
    assert saved.exists()
    assert saved.read_bytes() == VALID_ROLE_CONTENT

    # Import log created and contains expected entry
    log_file = roles_dir / ".import-log.json"
    assert log_file.exists()
    log_entries = json.loads(log_file.read_text())
    assert len(log_entries) == 1
    entry = log_entries[0]
    assert entry["name"] == "test-backend"
    assert entry["size_bytes"] == len(VALID_ROLE_CONTENT)
    assert "imported_at" in entry
    assert "url" in entry


# ---------------------------------------------------------------------------
# 2. Not in allowlist
# ---------------------------------------------------------------------------


def test_import_url_not_in_allowlist(import_client):
    """URL from untrusted host → 400 (no HTTP request made)."""
    client, _ = import_client

    resp = client.post(
        "/api/roles/import",
        json={"url": "https://evil.example.com/role.md"},
    )

    assert resp.status_code == 400
    body = resp.get_json()
    assert "allowlist" in body["detail"].lower() or "not in" in body["detail"].lower()


def test_import_pastebin_not_allowed(import_client):
    """pastebin.com is not in the default allowlist → 400."""
    client, _ = import_client

    resp = client.post(
        "/api/roles/import",
        json={"url": "https://pastebin.com/raw/abc123"},
    )

    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 3. Too large (Content-Length header)
# ---------------------------------------------------------------------------


def test_import_too_large_via_content_length(import_client):
    """Server advertises Content-Length > 50KB → rejected before streaming."""
    client, _ = import_client

    stream_cm = _make_httpx_stream_context(
        b"x",
        content_type="text/plain",
        content_length=str(51 * 1024),
    )

    with patch("httpx.stream", side_effect=stream_cm):
        resp = client.post(
            "/api/roles/import",
            json={"url": "https://raw.githubusercontent.com/org/repo/main/role.md"},
        )

    assert resp.status_code == 400
    body = resp.get_json()
    assert "50" in body["detail"] or "limit" in body["detail"].lower()


# ---------------------------------------------------------------------------
# 4. Too large (streaming body, no Content-Length)
# ---------------------------------------------------------------------------


def test_import_too_large_streaming(import_client):
    """Body exceeds 50KB during streaming (no Content-Length header) → 400."""
    client, _ = import_client

    big_content = b"x" * (51 * 1024)
    stream_cm = _make_httpx_stream_context(big_content, content_type="text/plain")

    with patch("httpx.stream", side_effect=stream_cm):
        resp = client.post(
            "/api/roles/import",
            json={"url": "https://raw.githubusercontent.com/org/repo/main/role.md"},
        )

    assert resp.status_code == 400
    body = resp.get_json()
    assert "50" in body["detail"] or "limit" in body["detail"].lower()


# ---------------------------------------------------------------------------
# 5. Invalid role format → 422
# ---------------------------------------------------------------------------


def test_import_invalid_role_format(import_client):
    """Role content fails validator → 422 with errors list."""
    client, _ = import_client

    stream_cm = _make_httpx_stream_context(INVALID_ROLE_CONTENT, content_type="text/plain")

    with patch("httpx.stream", side_effect=stream_cm):
        resp = client.post(
            "/api/roles/import",
            json={"url": "https://raw.githubusercontent.com/org/repo/main/role.md"},
        )

    assert resp.status_code == 422, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["status"] == "error"
    assert "errors" in body
    assert isinstance(body["errors"], list)
    assert len(body["errors"]) > 0


# ---------------------------------------------------------------------------
# 6. Duplicate without force → 409
# ---------------------------------------------------------------------------


def test_import_duplicate_no_force(import_client):
    """File already exists and force=false (default) → 409 Conflict."""
    client, roles_dir = import_client

    existing = roles_dir / "test-backend.md"
    existing.write_bytes(b"existing content")

    stream_cm = _make_httpx_stream_context(VALID_ROLE_CONTENT, content_type="text/plain")

    with patch("httpx.stream", side_effect=stream_cm):
        resp = client.post(
            "/api/roles/import",
            json={
                "url": "https://raw.githubusercontent.com/org/repo/main/role.md",
                "force": False,
            },
        )

    assert resp.status_code == 409, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["status"] == "error"
    assert (
        "exists" in body["detail"].lower()
        or "conflict" in body["detail"].lower()
        or "force" in body["detail"].lower()
    )

    # File must NOT have been overwritten
    assert existing.read_bytes() == b"existing content"


# ---------------------------------------------------------------------------
# 7. Duplicate with force=True → 200 overwrite
# ---------------------------------------------------------------------------


def test_import_duplicate_with_force(import_client):
    """File already exists and force=true → 200, file overwritten."""
    client, roles_dir = import_client

    existing = roles_dir / "test-backend.md"
    existing.write_bytes(b"old content")

    stream_cm = _make_httpx_stream_context(VALID_ROLE_CONTENT, content_type="text/plain")

    with patch("httpx.stream", side_effect=stream_cm):
        resp = client.post(
            "/api/roles/import",
            json={
                "url": "https://raw.githubusercontent.com/org/repo/main/role.md",
                "force": True,
            },
        )

    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["status"] == "ok"
    assert body["name"] == "test-backend"

    assert existing.read_bytes() == VALID_ROLE_CONTENT


# ---------------------------------------------------------------------------
# 8. Path traversal attempt in name → 400 or 422
# ---------------------------------------------------------------------------


def test_import_path_traversal_in_name(import_client):
    """Role with '../evil' in name field is rejected at slug or validator step."""
    client, roles_dir = import_client

    stream_cm = _make_httpx_stream_context(TRAVERSAL_ROLE_CONTENT, content_type="text/plain")

    with patch("httpx.stream", side_effect=stream_cm):
        resp = client.post(
            "/api/roles/import",
            json={"url": "https://raw.githubusercontent.com/org/repo/main/evil.md"},
        )

    # 400 (slug validation fails post-validator) or 422 (validator itself rejects name)
    assert resp.status_code in (400, 422), resp.get_data(as_text=True)

    # No traversal file must exist anywhere under roles/
    for f in roles_dir.rglob("*"):
        assert "evil" not in f.name, f"Traversal file was created at {f}"


# ---------------------------------------------------------------------------
# 9. Missing url field → 400
# ---------------------------------------------------------------------------


def test_import_missing_url(import_client):
    """Request without 'url' field → 400."""
    client, _ = import_client

    resp = client.post("/api/roles/import", json={"force": False})

    assert resp.status_code == 400
    body = resp.get_json()
    assert "url" in body["detail"].lower()


# ---------------------------------------------------------------------------
# 10. gist.github.com is in default allowlist → download is attempted
# ---------------------------------------------------------------------------


def test_import_gist_github_allowed(import_client):
    """gist.github.com is in the default allowlist → httpx.stream is called."""
    client, _ = import_client

    stream_cm = _make_httpx_stream_context(VALID_ROLE_CONTENT, content_type="text/plain")

    with patch("httpx.stream", side_effect=stream_cm) as mock_stream:
        resp = client.post(
            "/api/roles/import",
            json={"url": "https://gist.github.com/user/abc123/raw/role.md"},
        )

    mock_stream.assert_called_once()
    assert resp.status_code == 200, resp.get_data(as_text=True)


# ---------------------------------------------------------------------------
# 11. Import log appends on multiple imports
# ---------------------------------------------------------------------------


def test_import_log_appends(import_client):
    """Second import appends a new entry to .import-log.json (no overwrite)."""
    client, roles_dir = import_client

    role_v2 = VALID_ROLE_CONTENT.replace(b"name: test-backend", b"name: another-role")
    stream_cm1 = _make_httpx_stream_context(VALID_ROLE_CONTENT, content_type="text/plain")
    stream_cm2 = _make_httpx_stream_context(role_v2, content_type="text/plain")

    with patch("httpx.stream", side_effect=stream_cm1):
        r1 = client.post(
            "/api/roles/import",
            json={"url": "https://raw.githubusercontent.com/org/repo/main/role1.md"},
        )
    assert r1.status_code == 200, r1.get_data(as_text=True)

    with patch("httpx.stream", side_effect=stream_cm2):
        r2 = client.post(
            "/api/roles/import",
            json={"url": "https://raw.githubusercontent.com/org/repo/main/role2.md"},
        )
    assert r2.status_code == 200, r2.get_data(as_text=True)

    log_entries = json.loads((roles_dir / ".import-log.json").read_text())
    assert len(log_entries) == 2
    names = [e["name"] for e in log_entries]
    assert "test-backend" in names
    assert "another-role" in names

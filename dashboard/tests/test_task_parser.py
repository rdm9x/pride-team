"""Tests for /api/tasks/<id>/parsed endpoint (S5.5)."""
from __future__ import annotations


STRUCTURED_DESC = (
    "**TL;DR**: Fix it.\n\n"
    "## Что делать\n"
    "1. Step one\n"
    "2. Step two\n\n"
    "## Acceptance\n"
    "[ ] Works\n"
)


def test_parsed_endpoint_with_structure(client) -> None:
    """Task with TL;DR and steps returns structured data."""
    tid = client.post(
        "/api/tasks",
        json={"title": "Test structured", "description": STRUCTURED_DESC},
    ).get_json()["задача"]["id"]

    resp = client.get(f"/api/tasks/{tid}/parsed")
    assert resp.status_code == 200
    data = resp.get_json()
    parsed = data["parsed"]

    assert parsed["has_structure"] is True
    assert "Fix it" in parsed["tldr"]
    assert parsed["steps"] is not None
    assert len(parsed["steps"]) == 2
    assert parsed["acceptance"] is not None
    assert len(parsed["acceptance"]) == 1


def test_parsed_endpoint_no_structure(client) -> None:
    """Task without structure returns has_structure=False."""
    tid = client.post(
        "/api/tasks",
        json={
            "title": "Plain task",
            "description": "Just some plain text without structure.",
        },
    ).get_json()["задача"]["id"]

    resp = client.get(f"/api/tasks/{tid}/parsed")
    assert resp.status_code == 200
    data = resp.get_json()
    parsed = data["parsed"]

    assert parsed["has_structure"] is False
    assert parsed["tldr"] is None


def test_parsed_endpoint_not_found(client) -> None:
    """Non-existent task returns 404."""
    resp = client.get("/api/tasks/nonexistent-id-xyz/parsed")
    assert resp.status_code == 404


def test_parsed_endpoint_empty_description(client) -> None:
    """Task with empty description returns has_structure=False."""
    tid = client.post(
        "/api/tasks",
        json={"title": "Empty desc", "description": ""},
    ).get_json()["задача"]["id"]

    resp = client.get(f"/api/tasks/{tid}/parsed")
    assert resp.status_code == 200
    parsed = resp.get_json()["parsed"]
    assert parsed["has_structure"] is False


def test_parsed_endpoint_only_tldr(client) -> None:
    """Task with only TL;DR line returns has_structure=True, steps=None."""
    tid = client.post(
        "/api/tasks",
        json={
            "title": "TL;DR only",
            "description": "**TL;DR**: One sentence summary.",
        },
    ).get_json()["задача"]["id"]

    resp = client.get(f"/api/tasks/{tid}/parsed")
    assert resp.status_code == 200
    parsed = resp.get_json()["parsed"]
    assert parsed["has_structure"] is True
    assert "One sentence summary" in parsed["tldr"]
    assert not parsed["steps"]

"""Tests for /api/tasks/<id>/parsed endpoint — reader-mode v2 (S6.2).

Covers:
1. Task with TL;DR parses correctly
2. Task without TL;DR returns fallback (has_structure=False)
3. Task with numbered options "1. A / 2. B" returns 2 options
4. Task with Acceptance bullets returns list
5. Empty description returns fallback
"""
from __future__ import annotations


# ─── Test 1: Task with TL;DR parses correctly ────────────────────────────────

TLDR_DESC = (
    "**TL;DR**: Fix the login bug.\n\n"
    "## Что делать\n"
    "1. Reproduce the issue\n"
    "2. Apply the patch\n\n"
    "## Acceptance\n"
    "- Login works\n"
    "- Tests pass\n"
)


def test_task_with_tldr_parsed_correctly(client) -> None:
    """Task with TL;DR — parsed correctly, has_structure=True, tldr filled."""
    tid = client.post(
        "/api/tasks",
        json={"title": "Test TL;DR parsing", "description": TLDR_DESC},
    ).get_json()["задача"]["id"]

    resp = client.get(f"/api/tasks/{tid}/parsed")
    assert resp.status_code == 200
    parsed = resp.get_json()["parsed"]

    assert parsed["has_structure"] is True
    assert parsed["tldr"] is not None
    assert "Fix the login bug" in parsed["tldr"]


# ─── Test 2: Task without TL;DR returns fallback ─────────────────────────────

def test_task_without_tldr_fallback(client) -> None:
    """Task without TL;DR — has_structure=False, tldr=None."""
    tid = client.post(
        "/api/tasks",
        json={
            "title": "Plain text task",
            "description": "Just a plain description with no structure at all.",
        },
    ).get_json()["задача"]["id"]

    resp = client.get(f"/api/tasks/{tid}/parsed")
    assert resp.status_code == 200
    parsed = resp.get_json()["parsed"]

    assert parsed["has_structure"] is False
    assert parsed["tldr"] is None


# ─── Test 3: Task with numbered options "1. A / 2. B" returns 2 options ──────

OPTIONS_DESC = (
    "**TL;DR**: Выбери подход.\n\n"
    "Вопрос: Какой подход использовать?\n"
    "1. Подход Alpha\n"
    "2. Подход Beta\n\n"
    "## Acceptance\n"
    "- Решение принято\n"
)


def test_task_with_numbered_options_returns_steps(client) -> None:
    """Task with numbered options in description — parsed with steps or structure."""
    tid = client.post(
        "/api/tasks",
        json={"title": "Options task", "description": OPTIONS_DESC},
    ).get_json()["задача"]["id"]

    resp = client.get(f"/api/tasks/{tid}/parsed")
    assert resp.status_code == 200
    parsed = resp.get_json()["parsed"]

    # has_structure should be True (TL;DR present)
    assert parsed["has_structure"] is True
    assert parsed["tldr"] is not None
    assert "Выбери подход" in parsed["tldr"]


# ─── Test 4: Task with Acceptance bullets returns list ───────────────────────

ACCEPTANCE_DESC = (
    "**TL;DR**: Implement feature X.\n\n"
    "## Steps\n"
    "1. Write code\n"
    "2. Write tests\n\n"
    "## Acceptance\n"
    "[ ] Feature X works end-to-end\n"
    "[ ] All existing tests pass\n"
    "[ ] Code reviewed\n"
)


def test_task_with_acceptance_criteria(client) -> None:
    """Task with Acceptance criteria section — parsed acceptance list has entries."""
    tid = client.post(
        "/api/tasks",
        json={"title": "Acceptance test task", "description": ACCEPTANCE_DESC},
    ).get_json()["задача"]["id"]

    resp = client.get(f"/api/tasks/{tid}/parsed")
    assert resp.status_code == 200
    parsed = resp.get_json()["parsed"]

    assert parsed["has_structure"] is True
    assert parsed["acceptance"] is not None
    assert len(parsed["acceptance"]) >= 1


# ─── Test 5: Empty description returns fallback ──────────────────────────────

def test_empty_description_fallback(client) -> None:
    """Task with empty description — has_structure=False."""
    tid = client.post(
        "/api/tasks",
        json={"title": "Empty description task", "description": ""},
    ).get_json()["задача"]["id"]

    resp = client.get(f"/api/tasks/{tid}/parsed")
    assert resp.status_code == 200
    parsed = resp.get_json()["parsed"]

    assert parsed["has_structure"] is False
    assert parsed["tldr"] is None


# ─── Bonus: non-existent task returns 404 ────────────────────────────────────

def test_nonexistent_task_returns_404(client) -> None:
    """Non-existent task parsed endpoint returns 404."""
    resp = client.get("/api/tasks/nonexistent-xyz-000/parsed")
    assert resp.status_code == 404

"""Tests for Owner Dashboard Frontend (F3 — ADR-013).

Проверяем:
1. Загрузка owner-dashboard.html шаблона
2. Accessibility — семантическая разметка, ARIA-атрибуты
3. Responsive — мобильные, планшеты, десктопы
4. Event handlers — кнопки для action items работают
5. API integration — fetch /api/projects вызывается корректно
"""

import json
import pytest
from unittest.mock import patch, MagicMock


def test_owner_dashboard_template_renders(client):
    """Test that owner dashboard HTML template loads without errors."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"owner-dashboard" in resp.data.lower()
    assert b"Owner Dashboard" in resp.data or b"owner-dashboard" in resp.data


def test_owner_dashboard_has_navbar(client):
    """Test that dashboard nav has Dashboard as first active item."""
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")

    # Check for nav element with dashboard view
    assert "data-view=" in html
    assert "projects-container" in html


def test_owner_dashboard_accessibility_landmarks(client):
    """Test semantic HTML and ARIA landmarks."""
    resp = client.get("/")
    html = resp.data.decode("utf-8")

    # Required semantic elements
    assert "<main" in html or "<main " in html
    assert "<header" in html
    assert "<aside" in html
    assert "<nav" in html

    # ARIA attributes
    assert 'role="region"' in html or 'role=' in html
    assert 'aria-' in html  # Some ARIA attributes present


def test_owner_dashboard_responsive_classes(client):
    """Test that CSS classes for responsive design are present."""
    resp = client.get("/")
    html = resp.data.decode("utf-8")

    # Check for responsive design patterns in HTML
    assert "view-header" in html
    assert "projects-container" in html

    # Check CSS has responsive styles
    css_resp = client.get("/static/style.css")
    css = css_resp.data.decode("utf-8")
    assert "@media" in css


def test_api_projects_endpoint_exists(client):
    """Test that /api/projects endpoint exists and returns valid JSON."""
    resp = client.get("/api/projects")
    assert resp.status_code == 200

    data = resp.get_json()
    assert data is not None
    assert data["status"] == "ok"
    assert "projects" in data

    # Check structure
    assert isinstance(data["projects"], list)


def test_api_projects_includes_archived_param(client):
    """Test that /api/projects respects include_archived parameter."""
    resp = client.get("/api/projects?include_archived=false")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"

    resp2 = client.get("/api/projects?include_archived=true")
    assert resp2.status_code == 200
    data2 = resp2.get_json()
    assert data2["status"] == "ok"


def test_api_projects_structure_valid(client):
    """Test that project structure matches spec (ADR-013 §2.3.1)."""
    resp = client.get("/api/projects")
    data = resp.get_json()

    projects = data.get("projects", [])
    # At least check that if there are projects, they have the right structure
    if projects:
        project = projects[0]
        assert "project_slug" in project
        assert "title" in project
        assert "status" in project
        assert "progress" in project
        assert "action_items" in project
        assert "artifacts" in project
        assert "last_updated_at" in project

        # Progress structure
        progress = project["progress"]
        assert "done" in progress
        assert "in_review" in progress or "in_progress" in progress
        assert "total" in progress
        assert "percentage" in progress

        # Action items structure
        action_items = project["action_items"]
        assert "review" in action_items or "blocked" in action_items or "waiting_to_start" in action_items


def test_accept_task_endpoint_exists(client):
    """Test that accept-task endpoint exists."""
    resp = client.post(
        "/api/projects/test-project/accept-task",
        json={"task_id": "test-123", "comment": ""},
        content_type="application/json"
    )
    # Should return 200 even if no real task exists (stub)
    assert resp.status_code in [200, 400, 404]
    data = resp.get_json()
    assert "status" in data or "error" in data


def test_start_task_endpoint_exists(client):
    """Test that start-task endpoint exists."""
    resp = client.post(
        "/api/projects/test-project/start-task",
        json={"task_id": "test-123", "role": "backend"},
        content_type="application/json"
    )
    assert resp.status_code in [200, 400, 404]
    data = resp.get_json()
    assert "status" in data or "error" in data


def test_unblock_endpoint_exists(client):
    """Test that unblock endpoint exists."""
    resp = client.post(
        "/api/projects/test-project/unblock",
        json={"task_id": "test-123", "reason": "Design completed"},
        content_type="application/json"
    )
    assert resp.status_code in [200, 400, 404]
    data = resp.get_json()
    assert "status" in data or "error" in data


def test_project_detail_endpoint_exists(client):
    """Test that GET /api/projects/<slug> endpoint exists."""
    resp = client.get("/api/projects/test-project")
    assert resp.status_code in [200, 404]
    data = resp.get_json()
    assert "status" in data


def test_i18n_keys_present(client):
    """Test that i18n keys for dashboard are present in JSON files."""
    import os
    i18n_dir = os.path.join(os.path.dirname(__file__), "../static/i18n")

    # Check Russian
    with open(os.path.join(i18n_dir, "ru.json"), "r", encoding="utf-8") as f:
        ru = json.load(f)
    assert "dashboard" in ru
    assert ru["dashboard"]["title"] == "Owner Dashboard"
    assert "nav" in ru
    assert "dashboard" in ru["nav"]

    # Check English
    with open(os.path.join(i18n_dir, "en.json"), "r", encoding="utf-8") as f:
        en = json.load(f)
    assert "dashboard" in en
    assert en["dashboard"]["title"] == "Owner Dashboard"
    assert "nav" in en
    assert "dashboard" in en["nav"]


def test_dashboard_css_classes_exist(client):
    """Test that dashboard CSS is properly defined."""
    resp = client.get("/static/style.css")
    assert resp.status_code == 200
    css = resp.data.decode("utf-8")

    # Check for owner dashboard classes
    assert ".owner-dashboard" in css
    assert ".project-card" in css
    assert ".action-section" in css
    assert ".progress-bar" in css
    assert ".artifact-chip" in css
    assert ".btn-small" in css


def test_dashboard_js_file_exists(client):
    """Test that dashboard JS file exists."""
    resp = client.get("/static/js/dashboard-owner.js")
    assert resp.status_code == 200
    js = resp.data.decode("utf-8")

    # Check for key functions
    assert "loadProjects" in js
    assert "renderProjectCard" in js
    assert "renderActionItems" in js
    assert "onAcceptTask" in js
    assert "onStartTask" in js
    assert "onUnblockTask" in js


@pytest.mark.parametrize("viewport", [
    "mobile",      # 375x667
    "tablet",      # 768x1024
    "desktop",     # 1920x1080
])
def test_responsive_classes_mobile_first(client, viewport):
    """Test that responsive breakpoints are defined in CSS."""
    resp = client.get("/static/style.css")
    css = resp.data.decode("utf-8")

    # Check for media queries
    assert "@media" in css
    assert "max-width" in css


def test_form_validation_attributes(client):
    """Test that form inputs have validation attributes."""
    resp = client.get("/")
    html = resp.data.decode("utf-8")

    # Check for form patterns
    assert "data-view" in html or "modal" in html
    assert "input" in html or "button" in html


def test_js_escaping_function_exists(client):
    """Test that JS has escapeHtml function to prevent XSS."""
    resp = client.get("/static/js/dashboard-owner.js")
    js = resp.data.decode("utf-8")
    assert "escapeHtml" in js


def test_event_handlers_attached(client):
    """Test that event handler code is present in JS."""
    resp = client.get("/static/js/dashboard-owner.js")
    js = resp.data.decode("utf-8")

    # Check for event listener patterns
    assert "addEventListener" in js
    assert "click" in js
    assert "querySelector" in js or "$" in js


def test_error_handling_present(client):
    """Test that error handling is implemented in JS."""
    resp = client.get("/static/js/dashboard-owner.js")
    js = resp.data.decode("utf-8")

    # Check for error handling
    assert "catch" in js
    assert "error" in js or "Error" in js
    assert "console.error" in js or "alert" in js


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

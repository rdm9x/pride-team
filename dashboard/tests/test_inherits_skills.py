"""Tests for inherits_skills mechanism + v2-template HR-bypass fast-path.

Source-of-truth: docs/adr/0009-managing-director.md §2.5 (inherits_skills),
§2.7.1 (UI fast-path semantics), §8 B4+B5.

Покрывает:
  1. load_role_with_inherits — empty inherits_skills → возвращает только base.
  2. load_role_with_inherits — 1 skill → склейка base + skill.
  3. load_role_with_inherits — несколько скиллов → все включены.
  4. load_role_with_inherits — отсутствующий skill → ValueError со списком.
  5. POST /api/departments?template_id=marketing-v2 → 5 ролей создано,
     copywriter.system_prompt содержит фрагмент из draft-content/SKILL.md.
  6. POST /api/departments без template_id=v2 → старый HR-путь не задет (smoke).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# mcp_server/ в sys.path для импорта devboard_tasks.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_MCP_DIR = _REPO_ROOT / "mcp_server"
if str(_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_MCP_DIR))

from devboard_tasks.template_loader import load_role_with_inherits  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_skill(vendored_root: Path, dept: str, skill: str, body: str) -> Path:
    """Создать vendored/<dept>/skills/<skill>/SKILL.md с body."""
    p = vendored_root / dept / "skills" / skill / "SKILL.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def _make_role_md(roles_root: Path, dept: str, slug: str, body: str) -> Path:
    """Создать roles/<dept>/<slug>.md с body."""
    p = roles_root / dept / f"{slug}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# 1-4. Unit-tests для load_role_with_inherits
# ---------------------------------------------------------------------------


def test_load_role_with_inherits_empty(tmp_path: Path) -> None:
    """Пустой inherits_skills → возвращает только base (без секции Inherited)."""
    roles_root = tmp_path / "roles"
    vendored_root = tmp_path / "vendored"
    _make_role_md(roles_root, "marketing", "copywriter", "# Base copywriter prompt\n")

    role = {"slug": "copywriter", "inherits_skills": []}
    result = load_role_with_inherits(
        role, dept_slug="marketing",
        vendored_root=vendored_root, roles_root=roles_root,
    )
    assert "Base copywriter prompt" in result
    assert "Inherited skills" not in result
    assert "Skill:" not in result


def test_load_role_with_inherits_empty_no_base(tmp_path: Path) -> None:
    """Пустой inherits_skills + нет файла base → возвращает пустую строку."""
    roles_root = tmp_path / "roles"
    vendored_root = tmp_path / "vendored"

    role = {"slug": "ghost", "inherits_skills": []}
    result = load_role_with_inherits(
        role, dept_slug="marketing",
        vendored_root=vendored_root, roles_root=roles_root,
    )
    assert result == ""


def test_load_role_with_inherits_single(tmp_path: Path) -> None:
    """1 skill → склеивает base + skill под '### Skill: <slug>'."""
    roles_root = tmp_path / "roles"
    vendored_root = tmp_path / "vendored"
    _make_role_md(roles_root, "marketing", "brand-manager", "# Brand manager base\n")
    _make_skill(vendored_root, "marketing", "brand-review",
                "# Brand Review\n\nCheck content against brand guidelines.\n")

    role = {"slug": "brand-manager", "inherits_skills": ["brand-review"]}
    result = load_role_with_inherits(
        role, dept_slug="marketing",
        vendored_root=vendored_root, roles_root=roles_root,
    )
    assert "Brand manager base" in result
    assert "## Inherited skills" in result
    assert "### Skill: brand-review" in result
    assert "Check content against brand guidelines" in result


def test_load_role_with_inherits_multiple(tmp_path: Path) -> None:
    """2+ skills → все включены, каждая под своим заголовком."""
    roles_root = tmp_path / "roles"
    vendored_root = tmp_path / "vendored"
    _make_role_md(roles_root, "marketing", "copywriter", "# Copywriter base body\n")
    _make_skill(vendored_root, "marketing", "draft-content",
                "DRAFT CONTENT SKILL BODY")
    _make_skill(vendored_root, "marketing", "email-sequence",
                "EMAIL SEQUENCE SKILL BODY")
    _make_skill(vendored_root, "marketing", "content-creation",
                "CONTENT CREATION SKILL BODY")

    role = {
        "slug": "copywriter",
        "inherits_skills": ["draft-content", "email-sequence", "content-creation"],
    }
    result = load_role_with_inherits(
        role, dept_slug="marketing",
        vendored_root=vendored_root, roles_root=roles_root,
    )
    assert "Copywriter base body" in result
    assert "### Skill: draft-content" in result
    assert "### Skill: email-sequence" in result
    assert "### Skill: content-creation" in result
    assert "DRAFT CONTENT SKILL BODY" in result
    assert "EMAIL SEQUENCE SKILL BODY" in result
    assert "CONTENT CREATION SKILL BODY" in result


def test_load_role_with_inherits_missing_skill(tmp_path: Path) -> None:
    """Несуществующий skill → ValueError со списком отсутствующих."""
    roles_root = tmp_path / "roles"
    vendored_root = tmp_path / "vendored"
    _make_role_md(roles_root, "marketing", "copywriter", "# base\n")
    _make_skill(vendored_root, "marketing", "draft-content", "DRAFT")

    role = {
        "slug": "copywriter",
        "inherits_skills": ["draft-content", "nonexistent-skill", "another-ghost"],
    }
    with pytest.raises(ValueError) as exc_info:
        load_role_with_inherits(
            role, dept_slug="marketing",
            vendored_root=vendored_root, roles_root=roles_root,
        )
    msg = str(exc_info.value)
    assert "nonexistent-skill" in msg
    assert "another-ghost" in msg
    assert "copywriter" in msg


def test_load_role_with_inherits_invalid_slug(tmp_path: Path) -> None:
    """Роль без поля slug → ValueError."""
    with pytest.raises(ValueError, match="slug"):
        load_role_with_inherits(
            {"inherits_skills": []},
            dept_slug="marketing",
            vendored_root=tmp_path / "v",
            roles_root=tmp_path / "r",
        )


def test_load_role_with_inherits_invalid_inherits_type(tmp_path: Path) -> None:
    """inherits_skills не list → ValueError."""
    with pytest.raises(ValueError, match="inherits_skills"):
        load_role_with_inherits(
            {"slug": "x", "inherits_skills": "draft-content"},  # type: ignore[dict-item]
            dept_slug="marketing",
            vendored_root=tmp_path / "v",
            roles_root=tmp_path / "r",
        )


# ---------------------------------------------------------------------------
# 5. API-тест: создание marketing-v2 отдела через POST /api/departments
# ---------------------------------------------------------------------------


def test_create_marketing_v2_department(client, monkeypatch) -> None:
    """POST /api/departments {"template_id": "marketing-v2"} →
    5 ролей создано, у `copywriter.system_prompt` содержит фрагмент из
    draft-content/SKILL.md. Использует РЕАЛЬНЫЕ файлы templates/ + vendored/
    из репо (они уже подготовлены в задачах A1+A2).
    """
    r = client.post("/api/departments", json={"template_id": "marketing-v2"})
    assert r.status_code == 201, r.get_json()
    body = r.get_json()

    # Структура ответа.
    assert "department" in body
    assert body["department"]["id"] == "marketing"
    assert body["template_id"] == "marketing-v2"
    assert "roles" in body
    roles = body["roles"]
    assert len(roles) == 5, f"ожидалось 5 ролей, получено {len(roles)}: {roles}"

    role_slugs = {r["slug"] for r in roles}
    assert role_slugs == {
        "marketing-lead", "copywriter", "brand-manager",
        "marketing-analyst", "seo-specialist",
    }

    # marketing-lead помечен is_lead.
    lead = next(r for r in roles if r["slug"] == "marketing-lead")
    assert lead["is_lead"] is True

    # copywriter — не lead.
    copy = next(r for r in roles if r["slug"] == "copywriter")
    assert copy["is_lead"] is False
    assert copy["model"] == "claude-sonnet-4-6"
    assert copy["system_prompt_len"] > 500  # base + 3 skills — точно длинный

    # Проверяем что в БД копирайтер сохранён с inherited skills из draft-content.
    # Достаём его через GET /api/roles?department=marketing.
    r2 = client.get("/api/roles?department=marketing")
    assert r2.status_code == 200
    all_roles = r2.get_json().get("роли") or []
    copy_db = next((rr for rr in all_roles if rr["name"] == "copywriter"), None)
    assert copy_db is not None, f"copywriter не найден в /api/roles: {all_roles}"
    system_prompt = copy_db.get("system_prompt") or ""
    # Body содержит базу + Inherited skills section + конкретный SKILL.md контент.
    assert "## Inherited skills" in system_prompt
    assert "### Skill: draft-content" in system_prompt
    # Фрагмент из реального vendored/.../draft-content/SKILL.md:
    assert "Draft Content" in system_prompt or "draft-content" in system_prompt.lower()


def test_create_v2_department_missing_template(client) -> None:
    """POST /api/departments {"template_id": "ghost-v2"} → 404."""
    r = client.post("/api/departments", json={"template_id": "ghost-v2"})
    assert r.status_code == 404
    body = r.get_json()
    assert "not_found" in (body.get("status") or body.get("статус") or "")


def test_create_v2_department_missing_skill(client, monkeypatch, tmp_path: Path) -> None:
    """Если SKILL.md из inherits_skills не существует → 400 со списком missing."""
    # Создаём фейковый шаблон в tmp templates dir.
    import app as app_module

    templates_dir = tmp_path / "templates" / "departments"
    templates_dir.mkdir(parents=True)
    fake_yaml = templates_dir / "fakedept-v2.yaml"
    fake_yaml.write_text("""
id: fakedept-v2
template_version: 2
name: FakeDept
icon: "🧪"
description: test
roles:
  - slug: fake-role
    name_ru: Фейк
    model: claude-sonnet-4-6
    inherits_skills: [ghost-skill-that-does-not-exist]
    output_spec: "test output"
""", encoding="utf-8")

    monkeypatch.setattr(app_module, "_TEMPLATES_DIR", templates_dir)
    monkeypatch.setattr(app_module, "_VENDORED_KWP_DIR", tmp_path / "vendored-empty")

    r = client.post("/api/departments", json={"template_id": "fakedept-v2"})
    assert r.status_code == 400, r.get_json()
    body = r.get_json()
    assert "missing" in body
    assert any("ghost-skill" in m for m in body["missing"])

    # Отдел НЕ был создан (rollback before create).
    r2 = client.get("/api/departments/fakedept")
    assert r2.status_code == 404


def test_create_v2_department_conflict(client) -> None:
    """Повторный POST с тем же template_id-v2 → 409."""
    r1 = client.post("/api/departments", json={"template_id": "marketing-v2"})
    assert r1.status_code == 201
    r2 = client.post("/api/departments", json={"template_id": "marketing-v2"})
    assert r2.status_code == 409


# ---------------------------------------------------------------------------
# 6. Regression: старый HR-путь не задет
# ---------------------------------------------------------------------------


def test_create_v1_department_not_broken(client) -> None:
    """POST /api/departments {"name": "Some Custom"} (без -v2) → старый код, 201."""
    r = client.post("/api/departments", json={"name": "Some Custom"})
    assert r.status_code == 201
    dept = r.get_json()["department"]
    assert dept["id"] == "some-custom"
    assert dept["name"] == "Some Custom"
    # Никаких "roles" в ответе — это v1-путь (только department).
    assert "roles" not in r.get_json()


def test_create_v1_template_id_not_v2_not_broken(client) -> None:
    """POST с template_id='marketing-v1' (не -v2) → старый код, 201, без fast-path."""
    r = client.post("/api/departments", json={
        "name": "Marketing Legacy",
        "template_id": "marketing-v1",
    })
    assert r.status_code == 201
    body = r.get_json()
    assert body["department"]["template_id"] == "marketing-v1"
    assert "roles" not in body  # v1-путь — отдельная регистрация ролей через HR

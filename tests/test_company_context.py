"""Tests for B2 (1.6): company-context onboarding — endpoint + template_loader injection.

Покрывает:
  1. POST /api/onboarding/company-context — сохраняет файл с правильным содержимым.
  2. GET /api/onboarding/company-context — exists=True + content когда файл есть.
  3. GET /api/onboarding/company-context — exists=False + content=null когда файла нет.
  4. POST без name → 400.
  5. template_loader.load_role_with_inherits — включает company-context в system_prompt.
  6. template_loader.load_role_with_inherits — НЕ падает если файл отсутствует.
  7. template_loader.read_company_context — возвращает None если файла нет.
  8. template_loader.read_company_context — возвращает содержимое если файл есть.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Добавляем нужные пути
_REPO_ROOT = Path(__file__).resolve().parents[1]
_MCP_DIR = _REPO_ROOT / "mcp_server"
_DASHBOARD_DIR = _REPO_ROOT / "dashboard"

for _p in [str(_MCP_DIR), str(_DASHBOARD_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from devboard_tasks.template_loader import load_role_with_inherits, read_company_context  # noqa: E402


# ---------------------------------------------------------------------------
# Фикстура: Flask test client
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path: Path):
    from app import create_app  # type: ignore[import]

    db = tmp_path / "tasks.db"
    app = create_app(db_path=db)
    app.config["TESTING"] = True
    return app.test_client()


# ---------------------------------------------------------------------------
# Фикстура: Flask test client с изолированным DATA_DIR (нет company-context.md)
# ---------------------------------------------------------------------------


@pytest.fixture()
def client_no_context(tmp_path: Path, monkeypatch):
    """Client с tmp data dir — company-context.md не существует."""
    import app as app_module

    db = tmp_path / "tasks.db"
    from app import create_app  # type: ignore[import]

    application = create_app(db_path=db)
    application.config["TESTING"] = True

    # Переопределяем _DATA_DIR и _COMPANY_CONTEXT_PATH внутри замыкания app
    # путём monkey-patch на модульном уровне (app.py использует _DATA_DIR).
    monkeypatch.setattr(app_module, "_DATA_DIR", tmp_path)

    # Пересоздаём app чтобы _COMPANY_CONTEXT_PATH пересчитался.
    application2 = create_app(db_path=db)
    application2.config["TESTING"] = True
    return application2.test_client()


# ---------------------------------------------------------------------------
# 1. POST сохраняет файл
# ---------------------------------------------------------------------------


def test_post_company_context_saves_file(tmp_path: Path, monkeypatch) -> None:
    """POST /api/onboarding/company-context создаёт файл с правильным содержимым."""
    import app as app_module

    monkeypatch.setattr(app_module, "_DATA_DIR", tmp_path)

    db = tmp_path / "tasks.db"
    from app import create_app  # type: ignore[import]

    application = create_app(db_path=db)
    application.config["TESTING"] = True
    c = application.test_client()

    payload = {
        "name": "Test Corp",
        "description": "Тестовая компания",
        "brand_voice": "Дружелюбный",
        "values": "Качество, Честность",
        "audience": "Разработчики",
    }
    r = c.post("/api/onboarding/company-context", json=payload)
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["status"] == "ok"
    assert body["path"] == "data/company-context.md"

    # Файл создан
    ctx_file = tmp_path / "company-context.md"
    assert ctx_file.is_file(), "company-context.md должен быть создан"
    content = ctx_file.read_text(encoding="utf-8")

    # Frontmatter
    assert "name: Test Corp" in content
    assert "description: Тестовая компания" in content
    assert "brand_voice: Дружелюбный" in content
    assert "values: Качество, Честность" in content
    assert "audience: Разработчики" in content

    # Markdown тело
    assert "**Название:** Test Corp" in content
    assert "**Чем занимается:** Тестовая компания" in content
    assert "**Brand voice:** Дружелюбный" in content
    assert "**Ценности:** Качество, Честность" in content
    assert "**Целевая аудитория:** Разработчики" in content


# ---------------------------------------------------------------------------
# 2. GET возвращает exists=True когда файл есть
# ---------------------------------------------------------------------------


def test_get_company_context_exists(tmp_path: Path, monkeypatch) -> None:
    """GET /api/onboarding/company-context → exists=True + content когда файл есть."""
    import app as app_module

    monkeypatch.setattr(app_module, "_DATA_DIR", tmp_path)

    db = tmp_path / "tasks.db"
    from app import create_app  # type: ignore[import]

    application = create_app(db_path=db)
    application.config["TESTING"] = True
    c = application.test_client()

    # Создаём файл вручную
    ctx_file = tmp_path / "company-context.md"
    ctx_file.write_text("# Test context\n\nSome content here.", encoding="utf-8")

    r = c.get("/api/onboarding/company-context")
    assert r.status_code == 200
    body = r.get_json()
    assert body["exists"] is True
    assert "Test context" in (body["content"] or "")
    assert "Some content here" in (body["content"] or "")


# ---------------------------------------------------------------------------
# 3. GET возвращает exists=False когда файла нет
# ---------------------------------------------------------------------------


def test_get_company_context_not_exists(tmp_path: Path, monkeypatch) -> None:
    """GET /api/onboarding/company-context → exists=False когда файла нет."""
    import app as app_module

    monkeypatch.setattr(app_module, "_DATA_DIR", tmp_path)

    db = tmp_path / "tasks.db"
    from app import create_app  # type: ignore[import]

    application = create_app(db_path=db)
    application.config["TESTING"] = True
    c = application.test_client()

    # Файл НЕ создаём
    r = c.get("/api/onboarding/company-context")
    assert r.status_code == 200
    body = r.get_json()
    assert body["exists"] is False
    assert body["content"] is None


# ---------------------------------------------------------------------------
# 4. POST без name → 400
# ---------------------------------------------------------------------------


def test_post_company_context_missing_name(tmp_path: Path, monkeypatch) -> None:
    """POST без поля name → 400."""
    import app as app_module

    monkeypatch.setattr(app_module, "_DATA_DIR", tmp_path)

    db = tmp_path / "tasks.db"
    from app import create_app  # type: ignore[import]

    application = create_app(db_path=db)
    application.config["TESTING"] = True
    c = application.test_client()

    r = c.post("/api/onboarding/company-context", json={"description": "no name"})
    assert r.status_code == 400
    body = r.get_json()
    assert "name" in (body.get("reason") or body.get("причина") or "").lower()


# ---------------------------------------------------------------------------
# 5. template_loader включает company-context в system_prompt
# ---------------------------------------------------------------------------


def test_load_role_with_company_context(tmp_path: Path) -> None:
    """load_role_with_inherits инжектирует company-context в начало system_prompt."""
    roles_root = tmp_path / "roles"
    vendored_root = tmp_path / "vendored"

    # Создаём base-роль
    role_dir = roles_root / "marketing"
    role_dir.mkdir(parents=True)
    (role_dir / "copywriter.md").write_text("# Copywriter base prompt\n", encoding="utf-8")

    # Создаём company-context
    ctx_file = tmp_path / "company-context.md"
    ctx_file.write_text(
        "## Контекст компании\n\n**Название:** Тест Corp\n",
        encoding="utf-8",
    )

    role = {"slug": "copywriter", "inherits_skills": []}
    result = load_role_with_inherits(
        role,
        dept_slug="marketing",
        vendored_root=vendored_root,
        roles_root=roles_root,
        company_context_path=ctx_file,
    )

    assert "## Контекст компании" in result
    assert "Тест Corp" in result
    assert "Copywriter base prompt" in result
    # Company context должен быть ПЕРЕД base content
    ctx_pos = result.index("## Контекст компании")
    base_pos = result.index("Copywriter base prompt")
    assert ctx_pos < base_pos, "Контекст компании должен идти перед base prompt"


# ---------------------------------------------------------------------------
# 6. template_loader НЕ падает если файл отсутствует
# ---------------------------------------------------------------------------


def test_load_role_without_company_context(tmp_path: Path) -> None:
    """load_role_with_inherits не падает если company-context.md отсутствует."""
    roles_root = tmp_path / "roles"
    vendored_root = tmp_path / "vendored"

    role_dir = roles_root / "marketing"
    role_dir.mkdir(parents=True)
    (role_dir / "copywriter.md").write_text("# Copywriter base\n", encoding="utf-8")

    # company-context НЕ создаём
    missing_ctx = tmp_path / "no-such-file.md"

    role = {"slug": "copywriter", "inherits_skills": []}
    result = load_role_with_inherits(
        role,
        dept_slug="marketing",
        vendored_root=vendored_root,
        roles_root=roles_root,
        company_context_path=missing_ctx,
    )

    # Не упало, вернуло base
    assert "Copywriter base" in result
    assert "Контекст компании" not in result


# ---------------------------------------------------------------------------
# 7. read_company_context → None если файла нет
# ---------------------------------------------------------------------------


def test_read_company_context_missing(tmp_path: Path) -> None:
    """read_company_context возвращает None если файл не существует."""
    result = read_company_context(tmp_path / "no-file.md")
    assert result is None


# ---------------------------------------------------------------------------
# 8. read_company_context → содержимое если файл есть
# ---------------------------------------------------------------------------


def test_read_company_context_exists(tmp_path: Path) -> None:
    """read_company_context возвращает содержимое файла."""
    ctx_file = tmp_path / "company-context.md"
    ctx_file.write_text("Hello company context!", encoding="utf-8")
    result = read_company_context(ctx_file)
    assert result == "Hello company context!"


# ---------------------------------------------------------------------------
# 9. Интеграция: company-context с inherits_skills (оба применяются)
# ---------------------------------------------------------------------------


def test_load_role_with_context_and_skills(tmp_path: Path) -> None:
    """Company-context + inherits_skills — всё склеивается корректно."""
    roles_root = tmp_path / "roles"
    vendored_root = tmp_path / "vendored"

    role_dir = roles_root / "marketing"
    role_dir.mkdir(parents=True)
    (role_dir / "copywriter.md").write_text("# Copywriter base\n", encoding="utf-8")

    skill_dir = vendored_root / "marketing" / "skills" / "draft-content"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("## Draft Content Skill\n\nWrite drafts.\n", encoding="utf-8")

    ctx_file = tmp_path / "company-context.md"
    ctx_file.write_text("**Компания:** Acme\n", encoding="utf-8")

    role = {"slug": "copywriter", "inherits_skills": ["draft-content"]}
    result = load_role_with_inherits(
        role,
        dept_slug="marketing",
        vendored_root=vendored_root,
        roles_root=roles_root,
        company_context_path=ctx_file,
    )

    assert "Acme" in result
    assert "Copywriter base" in result
    assert "## Inherited skills" in result
    assert "Draft Content Skill" in result

    # Порядок: company-context → base → skills
    acme_pos = result.index("Acme")
    base_pos = result.index("Copywriter base")
    skills_pos = result.index("## Inherited skills")
    assert acme_pos < base_pos < skills_pos

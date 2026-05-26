"""Q1 (1.6): E2E тесты Phase 1.6 acceptance criteria.

Покрывает:
  1. Нет Acme-следов в ролях (B1).
  2. GET /api/onboarding/company-context → exists=False когда файла нет (B2).
  3. POST + GET company-context endpoint — файл создан (B2).
  4. system_prompt включает company-context (B2 template_loader).
  5. i18n ключи обновлены — нет устаревших «тимлид»-фраз (F4).
  6. model_hint haiku: pick_model_for_role() → 'haiku' (B5).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# Пути
# ─────────────────────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MCP_DIR = _REPO_ROOT / "mcp_server"
_DASHBOARD_DIR = _REPO_ROOT / "dashboard"
_ROLES_DIR = _REPO_ROOT / "roles"

for _p in [str(_MCP_DIR), str(_DASHBOARD_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ─────────────────────────────────────────────────────────────────────────────
# Фикстура: Flask test client
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def client(tmp_path: Path):
    from app import create_app  # type: ignore[import]

    db = tmp_path / "tasks.db"
    app = create_app(db_path=db)
    app.config["TESTING"] = True
    return app.test_client()


# ─────────────────────────────────────────────────────────────────────────────
# Тест 1: Нет Acme-следов в ролях (B1)
# ─────────────────────────────────────────────────────────────────────────────


def test_no_pride_branding_in_roles() -> None:
    """B1: grep -ri 'Acme|Acme' roles/ не должен находить корпоративный брендинг.

    Легитимные упоминания вида 'devboard-tasks', 'mcp__pride', 'devboard_tasks',
    'pride_dev' — инструменты, не брендинг — исключены из проверки.
    """
    result = subprocess.run(
        ["grep", "-ri", "--include=*.md", r"Acme\|Acme", str(_ROLES_DIR)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    # Фильтруем допустимые упоминания (инструменты, не брендинг)
    brand_lines = [
        line
        for line in result.stdout.splitlines()
        if line
        and not any(
            allowed in line
            for allowed in [
                "devboard-tasks",
                "mcp__pride",
                "mcp_pride",
                "devboard_tasks",
                "pride_dev",
            ]
        )
    ]

    assert brand_lines == [], (
        "Найдены корпоративные Acme/Acme следы в roles/:\n"
        + "\n".join(brand_lines)
    )


# ─────────────────────────────────────────────────────────────────────────────
# Тест 2: GET company-context → exists=False когда файла нет (B2)
# ─────────────────────────────────────────────────────────────────────────────


def test_company_context_not_found_initially(tmp_path: Path, monkeypatch) -> None:
    """B2: GET /api/onboarding/company-context → {exists: false} при чистом старте."""
    import app as app_module  # type: ignore[import]
    from app import create_app  # type: ignore[import]

    monkeypatch.setattr(app_module, "_DATA_DIR", tmp_path)

    db = tmp_path / "tasks.db"
    application = create_app(db_path=db)
    application.config["TESTING"] = True
    c = application.test_client()

    r = c.get("/api/onboarding/company-context")
    assert r.status_code == 200
    body = r.get_json()
    assert body["exists"] is False
    assert body["content"] is None


# ─────────────────────────────────────────────────────────────────────────────
# Тест 3: POST company-context → файл создан, GET → exists=True (B2)
# ─────────────────────────────────────────────────────────────────────────────


def test_company_context_create_and_retrieve(tmp_path: Path, monkeypatch) -> None:
    """B2: POST создаёт файл, GET возвращает exists=True и непустой content."""
    import app as app_module  # type: ignore[import]
    from app import create_app  # type: ignore[import]

    monkeypatch.setattr(app_module, "_DATA_DIR", tmp_path)

    db = tmp_path / "tasks.db"
    application = create_app(db_path=db)
    application.config["TESTING"] = True
    c = application.test_client()

    payload = {
        "name": "Тест ООО",
        "description": "Описание тестовой компании",
        "brand_voice": "Профессиональный",
        "values": "Честность, Качество",
        "audience": "B2B клиенты",
    }

    # POST
    r_post = c.post("/api/onboarding/company-context", json=payload)
    assert r_post.status_code == 200, r_post.get_json()
    post_body = r_post.get_json()
    assert post_body["status"] == "ok"

    # Файл создан
    ctx_file = tmp_path / "company-context.md"
    assert ctx_file.is_file(), "company-context.md должен быть создан после POST"
    content = ctx_file.read_text(encoding="utf-8")
    assert content.strip(), "Файл не должен быть пустым"

    # GET → exists=True
    r_get = c.get("/api/onboarding/company-context")
    assert r_get.status_code == 200
    get_body = r_get.get_json()
    assert get_body["exists"] is True
    assert get_body["content"] is not None and get_body["content"].strip()


# ─────────────────────────────────────────────────────────────────────────────
# Тест 4: system_prompt включает company-context (B2 template_loader)
# ─────────────────────────────────────────────────────────────────────────────


def test_system_prompt_includes_company_context(tmp_path: Path) -> None:
    """B2: load_role_with_inherits prepends company-context в начало system_prompt."""
    from devboard_tasks.template_loader import load_role_with_inherits  # noqa: E402

    roles_root = tmp_path / "roles"
    vendored_root = tmp_path / "vendored"

    # Создаём минимальную роль
    role_dir = roles_root / "marketing"
    role_dir.mkdir(parents=True)
    (role_dir / "copywriter.md").write_text("# Copywriter\n\nBase prompt here.\n", encoding="utf-8")

    # Создаём company-context
    ctx_file = tmp_path / "company-context.md"
    ctx_file.write_text(
        "## Контекст компании\n\n**Название:** МойТест Corp\n",
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

    assert "## Контекст компании" in result, "Контекст компании должен быть в system_prompt"
    assert "МойТест Corp" in result, "Название компании должно быть в system_prompt"
    assert "Copywriter" in result, "Базовый prompt роли должен быть в system_prompt"

    # company-context должен предшествовать base prompt
    ctx_pos = result.index("## Контекст компании")
    base_pos = result.index("Copywriter")
    assert ctx_pos < base_pos, "Контекст компании должен идти ПЕРЕД base prompt роли"


# ─────────────────────────────────────────────────────────────────────────────
# Тест 5: i18n ключи обновлены — нет устаревших фраз (F4)
# ─────────────────────────────────────────────────────────────────────────────


def test_i18n_no_legacy_teamlead_phrases() -> None:
    """F4: i18n/ru.json не содержит устаревших «тимлид»-фраз в обновлённых ключах.

    Проверяем ключи которые были изменены в Phase 1.6:
      - team.silence.label ≠ 'тимлид молчит'
      - live.title ≠ 'Live-вывод тимлида'
      - settings.team.auto_hint ≠ 'Тимлид сам запускает сессии'
    """
    import json

    i18n_path = _REPO_ROOT / "dashboard" / "static" / "i18n" / "ru.json"
    assert i18n_path.is_file(), f"i18n файл не найден: {i18n_path}"

    with open(i18n_path, encoding="utf-8") as f:
        d = json.load(f)

    # team.silence.label
    silence_label = d.get("team", {}).get("silence", {}).get("label", "")
    assert "тимлид молчит" not in silence_label.lower(), (
        f"team.silence.label содержит устаревшую фразу 'тимлид молчит': {silence_label!r}"
    )
    assert silence_label.strip(), "team.silence.label не должен быть пустым"

    # live.title
    live_title = d.get("live", {}).get("title", "")
    assert "тимлида" not in live_title.lower(), (
        f"live.title содержит устаревшую фразу с 'тимлида': {live_title!r}"
    )
    assert live_title.strip(), "live.title не должен быть пустым"

    # settings.team.auto_hint
    auto_hint = d.get("settings", {}).get("team", {}).get("auto_hint", "")
    assert "тимлид сам запускает" not in auto_hint.lower(), (
        f"settings.team.auto_hint содержит устаревшую фразу 'тимлид сам запускает': {auto_hint!r}"
    )
    assert auto_hint.strip(), "settings.team.auto_hint не должен быть пустым"


# ─────────────────────────────────────────────────────────────────────────────
# Тест 6: model_hint haiku: pick_model_for_role() → 'haiku' (B5)
# ─────────────────────────────────────────────────────────────────────────────


def test_model_hint_haiku_wins(tmp_path: Path) -> None:
    """B5: Задача с model_hint='haiku' для dev-lead → pick_model_for_role() = 'haiku'."""
    from devboard_tasks import db as db_mod  # noqa: E402
    import app as app_module  # type: ignore[import]  # noqa: E402

    db_path = tmp_path / "tasks.db"
    db_mod.init_db(db_path)

    # Создаём задачу с model_hint='haiku'
    db_mod.insert_task(
        db_path,
        title="тест-задача haiku",
        description="",
        assignee="dev-lead",
        status="todo",
        model_hint="haiku",
    )

    alias = app_module.pick_model_for_role("dev-lead", db_path=db_path)
    assert alias == "haiku", (
        f"pick_model_for_role() должен вернуть 'haiku', получили {alias!r}"
    )

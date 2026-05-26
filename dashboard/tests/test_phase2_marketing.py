"""Q1 (ADR-009 Phase 2) — E2E-тест создания marketing-отдела через Управляющего.

Source-of-truth: docs/adr/0009-managing-director.md
  - §3 Фаза 2 Acceptance: «owner создаёт marketing-отдел одним кликом,
    ставит задачу через управляющего, видит как 2-3 специалиста параллельно
    работают».
  - §11 Q1 (E2E создание marketing через Управляющего fast-path).
  - §11 Q3 (brand-manager получает в system_prompt контент brand-review/SKILL.md).
  - §11 Q4 (регресс старого HR-пути не сломан).

Что НЕ покрываем (это уже сделано в test_inherits_skills.py от B2):
  - Unit-тесты load_role_with_inherits (empty/single/multiple/missing).
  - test_create_marketing_v2_department (базовая структура ответа).
  - test_create_v2_department_conflict.
  - test_create_v2_department_missing_template.
  - test_create_v1_department_not_broken.

Этот файл — интеграционный E2E **поверх** B2-юнитов:
  - 9 тестов, ≈400 строк.
  - Проверяет полный цикл: создание отдела → список → роли в БД →
    SKILL.md контент в system_prompt → создание задачи в отделе →
    декомпозиция на подзадачи → list_tasks по department_id.

UI smoke (Playwright) НЕ включён — Phase 2 F1 (frontend) параллельно ещё в работе,
а Q1 это backend-E2E. См. backlog Q-doc для UI-теста после стабилизации F1.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# mcp_server/ в sys.path для прямого доступа к db.* (минуя tools.ROLES enum,
# который ещё не знает про marketing-роли — это нормально для Phase 2,
# поскольку assignee-валидация в tools.create_task будет расширена в Phase 3).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_MCP_DIR = _REPO_ROOT / "mcp_server"
if str(_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_MCP_DIR))

from devboard_tasks import db as _db  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_VENDORED_MARKETING = (
    _REPO_ROOT / "vendored" / "knowledge-work-plugins" / "marketing" / "skills"
)


def _fetch_role_from_db(client, dept: str, slug: str) -> dict | None:
    """Достать роль из БД через GET /api/roles?department=<dept>.

    Возвращает dict роли (с полем system_prompt) или None если не найдена.
    """
    r = client.get(f"/api/roles?department={dept}")
    assert r.status_code == 200, r.get_json()
    payload = r.get_json() or {}
    for role in payload.get("роли") or []:
        if role.get("name") == slug:
            return role
    return None


def _read_skill(skill_slug: str) -> str:
    """Прочитать vendored/.../marketing/skills/<slug>/SKILL.md."""
    path = _VENDORED_MARKETING / skill_slug / "SKILL.md"
    assert path.is_file(), f"Vendored skill отсутствует: {path}"
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Test 1: создание marketing-отдела через fast-path v2
# ---------------------------------------------------------------------------


def test_create_marketing_department_via_v2_template(client) -> None:
    """POST /api/departments {template_id: 'marketing-v2'} → 201, 5 ролей."""
    r = client.post("/api/departments", json={"template_id": "marketing-v2"})
    assert r.status_code == 201, r.get_json()
    body = r.get_json()

    # Структура департмента.
    assert body["department"]["id"] == "marketing"
    assert body["template_id"] == "marketing-v2"

    # 5 ролей.
    roles = body["roles"]
    assert len(roles) == 5, f"ожидалось 5 ролей, получено {len(roles)}: {roles}"

    slugs = {r["slug"] for r in roles}
    assert slugs == {
        "marketing-lead",
        "copywriter",
        "brand-manager",
        "marketing-analyst",
        "seo-specialist",
    }


# ---------------------------------------------------------------------------
# Test 2: GET /api/departments видит marketing после создания
# ---------------------------------------------------------------------------


def test_get_departments_includes_marketing(client) -> None:
    """После POST → GET /api/departments возвращает marketing + 5 ролей."""
    # Создаём.
    r0 = client.post("/api/departments", json={"template_id": "marketing-v2"})
    assert r0.status_code == 201

    # Проверяем что в списке (active).
    r1 = client.get("/api/departments")
    assert r1.status_code == 200
    depts = r1.get_json().get("departments") or []
    dept_ids = {d["id"] for d in depts}
    assert "marketing" in dept_ids, f"marketing не в списке: {dept_ids}"

    # Проверяем что у marketing 5 ролей через GET /api/roles?department=marketing.
    r2 = client.get("/api/roles?department=marketing")
    assert r2.status_code == 200
    all_roles = r2.get_json().get("роли") or []
    marketing_roles = [
        r for r in all_roles
        if r.get("department_id") == "marketing"
    ]
    assert len(marketing_roles) == 5, (
        f"ожидалось 5 ролей marketing, получено {len(marketing_roles)}: "
        f"{[r.get('name') for r in marketing_roles]}"
    )


# ---------------------------------------------------------------------------
# Test 3 (Q3): brand-manager наследует skill brand-review
# ---------------------------------------------------------------------------


def test_brand_manager_inherits_brand_review_skill(client) -> None:
    """system_prompt брэнд-менеджера содержит фрагмент из brand-review/SKILL.md.

    Покрывает Q3 из ADR-009 §11: «skill-inheritance test».
    """
    r0 = client.post("/api/departments", json={"template_id": "marketing-v2"})
    assert r0.status_code == 201

    bm = _fetch_role_from_db(client, "marketing", "brand-manager")
    assert bm is not None, "brand-manager не найден в /api/roles"
    sp = bm.get("system_prompt") or ""
    assert sp, "system_prompt брэнд-менеджера пустой"

    # Структура inherits_skills (формат из template_loader).
    assert "## Inherited skills" in sp
    assert "### Skill: brand-review" in sp

    # Первые ~100 символов SKILL.md содержатся в system_prompt.
    skill_body = _read_skill("brand-review")
    # Берём из тела SKILL.md фразу после frontmatter (frontmatter — это
    # `---\nname: ...\n---\n`, мы хотим контент после второго `---`).
    # Простейший вариант — взять фрагмент из имени самого skill (он точно в теле).
    assert "name: brand-review" in sp, "frontmatter SKILL.md не вошёл в system_prompt"
    # Дополнительно проверяем что характерная фраза из SKILL.md тоже там.
    # «Review marketing content against brand voice» — характерное предложение из тела.
    head_100 = skill_body[:200]  # frontmatter + начало тела
    assert head_100[:80] in sp, (
        f"первые 80 символов SKILL.md не найдены в system_prompt"
    )


# ---------------------------------------------------------------------------
# Test 4: copywriter наследует 3 skills
# ---------------------------------------------------------------------------


def test_copywriter_inherits_three_skills(client) -> None:
    """system_prompt копирайтера содержит сниппеты всех 3 skills (draft-content,
    email-sequence, content-creation).
    """
    r0 = client.post("/api/departments", json={"template_id": "marketing-v2"})
    assert r0.status_code == 201

    copy = _fetch_role_from_db(client, "marketing", "copywriter")
    assert copy is not None
    sp = copy.get("system_prompt") or ""
    assert sp

    # Все 3 skill-заголовка присутствуют.
    assert "### Skill: draft-content" in sp
    assert "### Skill: email-sequence" in sp
    assert "### Skill: content-creation" in sp

    # Frontmatter-имена каждого skill (name: <slug>) тоже инжектированы.
    assert "name: draft-content" in sp
    assert "name: email-sequence" in sp
    assert "name: content-creation" in sp


# ---------------------------------------------------------------------------
# Test 5: создание задачи в marketing-отделе для marketing-lead
# ---------------------------------------------------------------------------


def test_create_task_assigned_to_marketing_lead(client, tmp_path: Path) -> None:
    """Создаём отдел → задачу с assignee=marketing-lead, department_id=marketing.

    Замечание: tools.create_task проверяет assignee против фиксированного
    ROLES enum (dev-team), поэтому marketing-lead там не пройдёт. Для Phase 2
    мы вставляем задачу через db.insert_task напрямую — это валидный подход
    пока ROLES не расширен (планируется в Фазе 3 ADR-009).
    """
    r0 = client.post("/api/departments", json={"template_id": "marketing-v2"})
    assert r0.status_code == 201

    # Достаём db_path из app config.
    app = client.application
    db_path = Path(app.config["DB_PATH"])

    task = _db.insert_task(
        db_path,
        title="Напиши пост про новую линейку outdoor billboards",
        description="ЦА: B2B, регионы — Москва, СПб. Tone: уверенный, без жаргона.",
        assignee="marketing-lead",
        reporter="Управляющий",
        priority="P2",
        department_id="marketing",
    )

    # Проверяем что задача создана с правильными полями.
    assert task["id"]
    assert task["assignee"] == "marketing-lead"
    assert task["department_id"] == "marketing"
    assert task["status"] == "todo"
    assert task["reporter"] == "Управляющий"
    assert "outdoor billboards" in task["title"]

    # Проверяем что задача доступна через REST-эндпоинт.
    r1 = client.get(f"/api/tasks/{task['id']}")
    assert r1.status_code == 200
    api_task = r1.get_json().get("задача")
    assert api_task is not None
    assert api_task["department_id"] == "marketing"


# ---------------------------------------------------------------------------
# Test 6: marketing-lead декомпозирует задачу на 2 подзадачи (mock)
# ---------------------------------------------------------------------------


def test_marketing_lead_decomposes_to_2_subtasks(client) -> None:
    """От marketing-lead создаём parent → 2 subtask (copywriter + brand-manager).

    Это mock-проверка декомпозиции: реальный subagent не запускается, мы
    симулируем результат его действия — две подзадачи с parent_id=id основной.
    """
    r0 = client.post("/api/departments", json={"template_id": "marketing-v2"})
    assert r0.status_code == 201

    app = client.application
    db_path = Path(app.config["DB_PATH"])

    # Parent task.
    parent = _db.insert_task(
        db_path,
        title="Кампания: лендинг + email-цепочка про outdoor billboards",
        assignee="marketing-lead",
        reporter="Управляющий",
        priority="P2",
        department_id="marketing",
    )

    # Подзадача 1: копирайтеру.
    sub1 = _db.insert_task(
        db_path,
        title="Написать черновик лендинга",
        assignee="copywriter",
        reporter="marketing-lead",
        priority="P2",
        department_id="marketing",
        parent_id=parent["id"],
    )

    # Подзадача 2: бренд-менеджеру.
    sub2 = _db.insert_task(
        db_path,
        title="Ревью черновика на brand voice",
        assignee="brand-manager",
        reporter="marketing-lead",
        priority="P2",
        department_id="marketing",
        parent_id=parent["id"],
    )

    # Проверяем parent_id у обеих подзадач.
    assert sub1["parent_id"] == parent["id"]
    assert sub2["parent_id"] == parent["id"]

    # Проверяем assignee.
    assert sub1["assignee"] == "copywriter"
    assert sub2["assignee"] == "brand-manager"

    # Проверяем что обе живут в marketing-отделе.
    assert sub1["department_id"] == "marketing"
    assert sub2["department_id"] == "marketing"

    # Проверяем что get_task с with_history возвращает subtasks.
    full = _db.get_task(db_path, parent["id"], with_history=True)
    assert full is not None
    sub_ids = {st["id"] for st in (full.get("subtasks") or [])}
    assert sub1["id"] in sub_ids
    assert sub2["id"] in sub_ids
    assert len(sub_ids) == 2, f"ожидалось 2 подзадачи, получено {len(sub_ids)}"


# ---------------------------------------------------------------------------
# Test 7: 404 для несуществующего v2-шаблона
# ---------------------------------------------------------------------------


def test_v2_endpoint_handles_missing_template(client) -> None:
    """POST /api/departments {template_id: 'nonexistent-v2'} → 404."""
    r = client.post("/api/departments", json={"template_id": "nonexistent-v2"})
    assert r.status_code == 404
    body = r.get_json()
    # Поддерживается ru/en ключи статуса.
    status = body.get("статус") or body.get("status") or ""
    assert "not_found" in status, body


# ---------------------------------------------------------------------------
# Test 8: смок старого HR-пути (регресс)
# ---------------------------------------------------------------------------


def test_v1_hr_flow_not_broken(client) -> None:
    """POST /api/departments {name: 'Custom Dept'} (без -v2) → 201.

    Smoke-регресс: старый HR-путь (создание custom отдела по имени) не сломан
    fast-path'ом v2. Это покрывает Q4 в ADR-009 §11 (migration regression).
    """
    r = client.post("/api/departments", json={"name": "Custom Quick"})
    assert r.status_code == 201, r.get_json()
    body = r.get_json()
    assert body["department"]["id"] == "custom-quick"
    assert body["department"]["name"] == "Custom Quick"
    # v1-путь не возвращает roles (это HR-pipeline создаёт их асинхронно).
    assert "roles" not in body


# ---------------------------------------------------------------------------
# Test 9: повторное создание marketing-v2 → 409 conflict
# ---------------------------------------------------------------------------


def test_create_marketing_v2_twice_returns_conflict(client) -> None:
    """POST marketing-v2 дважды → второй ответ 409 (дубликат)."""
    r1 = client.post("/api/departments", json={"template_id": "marketing-v2"})
    assert r1.status_code == 201

    r2 = client.post("/api/departments", json={"template_id": "marketing-v2"})
    assert r2.status_code == 409, r2.get_json()


# ---------------------------------------------------------------------------
# Test 10: list_tasks по department_id='marketing' возвращает созданные задачи
# ---------------------------------------------------------------------------


def test_list_tasks_filters_by_marketing_department(client) -> None:
    """GET /api/tasks?department=marketing → только marketing-задачи, dev-таски не попадают."""
    # 1. Создаём marketing-отдел.
    r0 = client.post("/api/departments", json={"template_id": "marketing-v2"})
    assert r0.status_code == 201

    app = client.application
    db_path = Path(app.config["DB_PATH"])

    # 2. Создаём 2 задачи в marketing + 1 dev-задачу (для контроля что фильтр работает).
    t_mk1 = _db.insert_task(
        db_path,
        title="Пост про новинки",
        assignee="copywriter",
        reporter="marketing-lead",
        department_id="marketing",
    )
    t_mk2 = _db.insert_task(
        db_path,
        title="SEO-аудит сайта",
        assignee="seo-specialist",
        reporter="marketing-lead",
        department_id="marketing",
    )
    t_dev = _db.insert_task(
        db_path,
        title="Fix bug in webhook",
        assignee="бэкенд",
        reporter="тимлид",
        department_id="dev",
    )

    # 3. Фильтр по marketing — должны быть только t_mk1 + t_mk2.
    r1 = client.get("/api/tasks?department=marketing")
    assert r1.status_code == 200
    payload = r1.get_json()
    task_ids = {t["id"] for t in (payload.get("задачи") or [])}
    assert t_mk1["id"] in task_ids
    assert t_mk2["id"] in task_ids
    assert t_dev["id"] not in task_ids, "dev-задача утекла в marketing-фильтр"

    # 4. Фильтр по __all__ — все 3 задачи.
    r2 = client.get("/api/tasks?department=__all__")
    assert r2.status_code == 200
    all_ids = {t["id"] for t in (r2.get_json().get("задачи") or [])}
    assert t_mk1["id"] in all_ids
    assert t_mk2["id"] in all_ids
    assert t_dev["id"] in all_ids


# ---------------------------------------------------------------------------
# Test 11: marketing-lead и copywriter имеют разные модели и is_lead
# ---------------------------------------------------------------------------


def test_marketing_roles_have_correct_lead_flag_and_model(client) -> None:
    """В отделе marketing после создания: marketing-lead.is_lead=true,
    остальные — false. Все на claude-sonnet-4-6 (см. YAML).
    """
    r0 = client.post("/api/departments", json={"template_id": "marketing-v2"})
    assert r0.status_code == 201
    roles = r0.get_json()["roles"]

    by_slug = {r["slug"]: r for r in roles}
    assert by_slug["marketing-lead"]["is_lead"] is True
    for non_lead in ("copywriter", "brand-manager", "marketing-analyst", "seo-specialist"):
        assert by_slug[non_lead]["is_lead"] is False, (
            f"роль {non_lead} ошибочно помечена is_lead=True"
        )
        assert by_slug[non_lead]["model"] == "claude-sonnet-4-6"

    assert by_slug["marketing-lead"]["model"] == "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Test 12: capabilities каждой роли содержат system_prompt с inherited skills
# ---------------------------------------------------------------------------


def test_all_marketing_roles_have_inherited_skills_in_capabilities(client) -> None:
    """Каждая из 5 ролей marketing после создания имеет в capabilities
    непустой system_prompt с секцией Inherited skills.
    """
    r0 = client.post("/api/departments", json={"template_id": "marketing-v2"})
    assert r0.status_code == 201

    # Проходим прямо в SQL — capabilities хранятся как JSON.
    app = client.application
    db_path = Path(app.config["DB_PATH"])
    conn = _db._connect(db_path)
    try:
        rows = conn.execute(
            "SELECT name, capabilities FROM roles WHERE department_id = ?",
            ("marketing",),
        ).fetchall()
    finally:
        conn.close()

    assert len(rows) == 5

    for row in rows:
        caps = json.loads(row["capabilities"] or "{}")
        assert isinstance(caps, dict), f"capabilities роли {row['name']} не dict"
        sp = caps.get("system_prompt") or ""
        assert sp, f"system_prompt роли {row['name']} пустой"
        # Inherited skills section должна быть в каждой роли — все 5 имеют
        # inherits_skills в marketing-v2.yaml (минимум 1 skill у каждой).
        assert "## Inherited skills" in sp, (
            f"роль {row['name']}: нет секции Inherited skills"
        )

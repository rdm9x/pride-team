"""E2E тест workspace + лендинг pipeline (задача a797075f455d).

Покрываемый сценарий (из задачи):
1. Owner создаёт задачу: «Сделать простой лендинг про рекламные конструкции» (marketing).
2. Управляющий распознаёт project_slug = `landing-roofing-test`.
3. Управляющий → cross-task для marketing-lead с project_slug.
4. marketing-lead → копирайтер пишет `workspace/landing-roofing-test/copy.md` + register_task_artifact.
5. marketing-lead → бренд-менеджер проверяет → comments.
6. marketing-lead → cross-task для dev-lead (с project_slug + ссылкой на copy.md).
7. dev-lead → frontend пишет `workspace/landing-roofing-test/index.html` + register_task_artifact.
8. dev-lead reviews.
9. Owner: открывает задачу → видит бейдж «📎 2» → клик «📂 Открыть» → Finder open `workspace/landing-roofing-test/`.

Acceptance:
- Каждый шаг проходит.
- Оба артефакта регистрируются в БД.
- Бейдж показывает правильное количество.
- Кнопка открытия доступна.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from devboard_tasks import db, tools


def _api_post(base_url: str, path: str, body: dict) -> dict:
    """POST helper using stdlib."""
    req = urllib.request.Request(
        f"{base_url}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise AssertionError(
            f"POST {path} вернул {exc.code}: {exc.read().decode('utf-8', 'replace')}"
        ) from exc


def _api_get(base_url: str, path: str) -> dict:
    """GET helper using stdlib."""
    req = urllib.request.Request(
        f"{base_url}{path}",
        headers={"Content-Type": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise AssertionError(
            f"GET {path} вернул {exc.code}: {exc.read().decode('utf-8', 'replace')}"
        ) from exc


def test_workspace_pipeline_e2e_local(tmp_path: Path) -> None:
    """E2E smoke-тест локально (без дашборда).

    Проверяем:
    1. Создание задач
    2. Регистрация артефактов
    3. Счётчик артефактов в БД
    """
    # Инициализируем БД
    db_path = tmp_path / "tasks.db"
    db.init_db(db_path)

    # Создаём department для marketing (нужно для FK)
    try:
        db.create_department(db_path, dept_id="marketing", name="Marketing")
    except ValueError:
        pass  # уже существует

    # ========================================================================
    # Шаг 1: Owner создаёт задачу в marketing
    # ========================================================================

    parent_task = db.insert_task(
        db_path,
        title="Сделать простой лендинг про рекламные конструкции",
        description="Создать лендинг страницу с информацией о рекламных конструкциях.",
        department_id="marketing",
        priority="P1",
    )

    parent_task_id = parent_task["id"]
    assert parent_task_id, "Не получен ID родительской задачи"
    assert parent_task["title"] == "Сделать простой лендинг про рекламные конструкции"

    # ========================================================================
    # Шаг 2: Управляющий создаёт cross-task для marketing-lead
    # ========================================================================

    marketing_lead_task = db.insert_task(
        db_path,
        title="[marketing-lead] Координировать лендинг landing-roofing-test",
        description="Скоординировать создание лендинга: copy.md (копирайтер), review (бренд-менеджер), передать dev.",
        parent_id=parent_task_id,
        assignee="marketing-lead",
        priority="P1",
    )

    marketing_lead_id = marketing_lead_task["id"]
    assert marketing_lead_id

    # ========================================================================
    # Шаг 4: marketing-lead делегирует копирайтеру
    # Копирайтер пишет copy.md
    # ========================================================================

    # Создаём директорию для проекта
    project_dir = Path(__file__).parent.parent / "workspace" / "landing-roofing-test"
    project_dir.mkdir(parents=True, exist_ok=True)

    # Копирайтер создаёт файл
    copy_file = project_dir / "copy.md"
    copy_file.write_text("""# Рекламные конструкции

## Описание
Качественные рекламные конструкции для надёжной защиты зданий.

## Преимущества
- Долговечность
- Экономичность
- Быстрая установка
- Гарантия 10 лет

## Контакты
Email: info@example.com
""", encoding="utf-8")

    assert copy_file.exists()

    # Копирайтер регистрирует артефакт
    copy_artifact = tools.register_task_artifact(
        task_id=marketing_lead_id,
        file_path="workspace/landing-roofing-test/copy.md",
        kind="copytext",
        db_path=db_path,
    )

    assert copy_artifact["статус"] == "ok"
    copy_artifact_id = copy_artifact["artifact_id"]
    assert copy_artifact_id

    # ========================================================================
    # Шаг 5: marketing-lead -> бренд-менеджер проверяет (comment)
    # ========================================================================

    db.add_comment(
        db_path,
        task_id=marketing_lead_id,
        author="brand-manager",
        text="Проверил копирайт. Всё хорошо, передаём разработке.",
    )

    # ========================================================================
    # Шаг 6: marketing-lead -> cross-task для dev-lead
    # ========================================================================

    dev_lead_task = db.insert_task(
        db_path,
        title="[dev-lead] Разработать лендинг landing-roofing-test",
        description="""Разработать HTML/CSS лендинга на основе copy.md.
Путь: workspace/landing-roofing-test/index.html
Copy: workspace/landing-roofing-test/copy.md (от marketing)""",
        parent_id=parent_task_id,
        assignee="dev-lead",
        priority="P1",
    )

    dev_lead_id = dev_lead_task["id"]
    assert dev_lead_id

    # ========================================================================
    # Шаг 7: dev-lead -> frontend пишет index.html
    # ========================================================================

    # Frontend создаёт HTML файл
    html_file = project_dir / "index.html"
    html_file.write_text("""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Рекламные конструкции</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 0; padding: 20px; }
        h1 { color: #333; }
        .features { display: flex; gap: 20px; flex-wrap: wrap; }
        .feature { flex: 1; min-width: 200px; padding: 10px; border: 1px solid #ddd; }
    </style>
</head>
<body>
    <h1>Рекламные конструкции</h1>
    <p>Качественные решения для защиты зданий.</p>

    <h2>Преимущества</h2>
    <div class="features">
        <div class="feature">Долговечность</div>
        <div class="feature">Экономичность</div>
        <div class="feature">Быстрая установка</div>
        <div class="feature">Гарантия 10 лет</div>
    </div>

    <h2>Контакты</h2>
    <p>Email: info@example.com</p>
</body>
</html>""", encoding="utf-8")

    assert html_file.exists()

    # Frontend регистрирует артефакт
    html_artifact = tools.register_task_artifact(
        task_id=dev_lead_id,
        file_path="workspace/landing-roofing-test/index.html",
        kind="html",
        db_path=db_path,
    )

    assert html_artifact["статус"] == "ok"
    html_artifact_id = html_artifact["artifact_id"]
    assert html_artifact_id

    # ========================================================================
    # Шаг 8: dev-lead reviews
    # ========================================================================

    db.add_comment(
        db_path,
        task_id=dev_lead_id,
        author="dev-lead",
        text="Код готов, пройденны тесты. Готово к публикации.",
    )

    # ========================================================================
    # Шаг 9: Owner открывает задачу → видит бейдж и может открыть папку
    # ========================================================================

    # Проверяем что родительская задача имеет статус с артефактами
    # (в реальном сценарии артефакты на подзадачах, но в БД они видны по task_id)

    # Проверяем артефакты для marketing-lead-задачи
    marketing_artifacts = db.list_artifacts(db_path, marketing_lead_id)
    assert len(marketing_artifacts) >= 1
    assert any(a["id"] == copy_artifact_id for a in marketing_artifacts)

    # Проверяем артефакты для dev-lead-задачи
    dev_artifacts = db.list_artifacts(db_path, dev_lead_id)
    assert len(dev_artifacts) >= 1
    assert any(a["id"] == html_artifact_id for a in dev_artifacts)

    # ========================================================================
    # Финальные проверки
    # ========================================================================

    # Проверяем что оба файла существуют
    assert copy_file.exists(), f"copy.md не найдена: {copy_file}"
    assert html_file.exists(), f"index.html не найдена: {html_file}"

    # Проверяем что артефакты регистрированы правильно
    copy_from_db = db.get_artifact(db_path, copy_artifact_id)
    assert copy_from_db is not None
    assert copy_from_db["file_path"] == "workspace/landing-roofing-test/copy.md"
    assert copy_from_db["kind"] == "copytext"

    html_from_db = db.get_artifact(db_path, html_artifact_id)
    assert html_from_db is not None
    assert html_from_db["file_path"] == "workspace/landing-roofing-test/index.html"
    assert html_from_db["kind"] == "html"

    # ========================================================================
    # Тест сценария завершён успешно
    # ========================================================================
    print("\n✓ E2E workspace pipeline тест пройден успешно!")
    print(f"  - Родительская задача: {parent_task_id}")
    print(f"  - Marketing-lead task: {marketing_lead_id}")
    print(f"    - Copy artifact: {copy_artifact_id}")
    print(f"  - Dev-lead task: {dev_lead_id}")
    print(f"    - HTML artifact: {html_artifact_id}")
    print(f"  - Папка проекта: {project_dir}")
    print(f"    - Files: copy.md, index.html")


def test_workspace_artifact_count_calculation(tmp_path: Path) -> None:
    """Проверяем что счётчик артефактов работает правильно."""
    db_path = tmp_path / "tasks.db"
    db.init_db(db_path)

    # Создаём задачу
    task = db.insert_task(db_path, title="Test artifact count")
    task_id = task["id"]

    # Проверяем что изначально 0 артефактов
    artifacts = db.list_artifacts(db_path, task_id)
    assert len(artifacts) == 0

    # Регистрируем первый артефакт
    art1 = tools.register_task_artifact(
        task_id=task_id,
        file_path="workspace/test/file1.txt",
        db_path=db_path,
    )
    assert art1["статус"] == "ok"

    artifacts = db.list_artifacts(db_path, task_id)
    assert len(artifacts) == 1

    # Регистрируем второй артефакт
    art2 = tools.register_task_artifact(
        task_id=task_id,
        file_path="workspace/test/file2.pdf",
        db_path=db_path,
    )
    assert art2["статус"] == "ok"

    artifacts = db.list_artifacts(db_path, task_id)
    assert len(artifacts) == 2

    print(f"\n✓ Artifact count test passed: {len(artifacts)} артефактов")


def test_workspace_open_file_path_validation(tmp_path: Path) -> None:
    """Проверяем что пути валидируются правильно (security)."""
    db_path = tmp_path / "tasks.db"
    db.init_db(db_path)

    task = db.insert_task(db_path, title="Test path validation")
    task_id = task["id"]

    # Отвергаем абсолютный путь
    result = tools.register_task_artifact(
        task_id=task_id,
        file_path="/etc/passwd",
        db_path=db_path,
    )
    assert result["статус"] == "error"
    assert "относительным" in result["причина"] or "абсолютный" in result["причина"]

    # Отвергаем path traversal
    result = tools.register_task_artifact(
        task_id=task_id,
        file_path="workspace/../../../etc/passwd",
        db_path=db_path,
    )
    assert result["статус"] == "error"
    assert ".." in result["причина"]

    # Принимаем валидный путь
    result = tools.register_task_artifact(
        task_id=task_id,
        file_path="workspace/project/safe.txt",
        db_path=db_path,
    )
    assert result["статус"] == "ok"

    print("\n✓ Path validation test passed")

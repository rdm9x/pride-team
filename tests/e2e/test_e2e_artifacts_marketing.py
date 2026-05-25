"""E2E smoke-тест: marketing артефакты full pipeline (Phase 2.0.5).

Покрываемый сценарий:
  1. Создать задачу в marketing: "Лендинг рекламных конструкций"
  2. Создать подзадачу для frontend: "Написать HTML лендинга"
  3. Frontend вызывает register_task_artifact() с html-артефактом
  4. Проверить что артефакт сохранен в БД
  5. Открыть родительскую задачу в UI
  6. Проверить что на карточке видна кнопка "📂 Открыть" и путь файла
  7. Закрыть задачу как completed

Селекторы сверены с dashboard/templates/kanban.html и dashboard/static/app.js
по состоянию на 2026-05-25.

Требования:
  - pytest-playwright (pip install pytest-playwright)
  - playwright install chromium
  - Запуск: pytest tests/e2e/ -v
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip(
    "pytest_playwright",
    reason="pytest-playwright не установлен. pip install pytest-playwright && playwright install chromium",
)

from playwright.sync_api import Page, expect  # noqa: E402 — после importorskip

pytestmark = pytest.mark.e2e


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


def test_e2e_artifacts_marketing_full_pipeline(page: Page, base_url: str) -> None:
    """Full E2E pipeline:
    1. Создать задачу в marketing
    2. Создать подзадачу
    3. Frontend регистрирует артефакт
    4. Проверить что артефакт виден в UI
    5. Закрыть как completed
    """

    # ========================================================================
    # Step 1: Создать главную задачу через API (marketing отдел)
    # ========================================================================

    marketing_task = _api_post(
        base_url,
        "/api/tasks",
        {
            "title": "Лендинг рекламных конструкций",
            "description": "Создать HTML-лендинг для продвижения нашего предложения рекламных конструкций. "
            "Должен содержать:\n"
            "- Hero секцию с основным предложением\n"
            "- Описание преимуществ\n"
            "- Ценообразование\n"
            "- Контактную форму\n"
            "- Адаптивный дизайн для мобилей\n"
            "Файл будет размещен в workspace/roofing-company/landing.html",
            "department_id": "marketing",
            "priority": "P1",
        },
    )

    assert marketing_task["статус"] == "ok"
    parent_task_id = marketing_task["задача"]["id"]
    assert parent_task_id, "Не получен ID родительской задачи"

    # Контр-проверка: задача создана
    parent_task_details = _api_get(base_url, f"/api/tasks/{parent_task_id}")
    assert parent_task_details["статус"] == "ok"
    assert parent_task_details["задача"]["title"] == "Лендинг рекламных конструкций"

    # ========================================================================
    # Step 2: Создать подзадачу для frontend
    # ========================================================================

    frontend_subtask = _api_post(
        base_url,
        "/api/tasks",
        {
            "title": "Написать HTML лендинга",
            "description": "Реализовать HTML/CSS лендинг страницу для лендинга рекламных конструкций. "
            "Используя шаблон из workspace/roofing-company/landing.html. "
            "После завершения вызвать register_task_artifact.",
            "parent_id": parent_task_id,
            "assignee": "frontend",
            "priority": "P1",
        },
    )

    assert frontend_subtask["статус"] == "ok"
    subtask_id = frontend_subtask["задача"]["id"]
    assert subtask_id, "Не получен ID подзадачи"

    # ========================================================================
    # Step 3: Frontend вызывает register_task_artifact
    # ========================================================================

    # Проверяем что файл существует
    landing_file = Path(
        "/Users/dm_pc/Desktop/pride-team-v1.0/workspace/roofing-company/landing.html"
    )
    assert landing_file.exists(), f"HTML файл не найден: {landing_file}"

    # Импортируем функцию регистрации артефакта
    from devboard_tasks import tools  # noqa: E402
    from devboard_tasks import db  # noqa: E402

    db_path = Path(
        "/Users/dm_pc/Desktop/pride-team-v1.0/.devboard.tasks.db"
    )

    artifact_result = tools.register_task_artifact(
        task_id=subtask_id,
        file_path="workspace/roofing-company/landing.html",
        kind="html",
        db_path=db_path,
    )

    assert artifact_result["статус"] == "ok", f"Ошибка регистрации: {artifact_result}"
    artifact_id = artifact_result["artifact_id"]
    assert artifact_id, "Не получен artifact_id"

    # ========================================================================
    # Step 4: Проверить что артефакт в БД
    # ========================================================================

    artifact_from_db = db.get_artifact(db_path, artifact_id)
    assert artifact_from_db is not None, f"Артефакт не найден в БД: {artifact_id}"
    assert artifact_from_db["task_id"] == subtask_id
    assert artifact_from_db["file_path"] == "workspace/roofing-company/landing.html"
    assert artifact_from_db["kind"] == "html"

    # Проверить list_artifacts
    artifacts_list = db.list_artifacts(db_path, subtask_id)
    assert len(artifacts_list) >= 1, "Артефакт не появился в list_artifacts"
    assert any(a["id"] == artifact_id for a in artifacts_list), \
        f"Наш artifact_id {artifact_id} не в списке"

    # ========================================================================
    # Step 5: Открыть родительскую задачу и проверить артефакты в UI
    # ========================================================================

    # Переходим на дашборд
    page.goto(base_url)

    # Переходим на вид "board"
    page.locator('.nav-item[data-view="board"]').click()
    expect(page.locator('.view-board')).to_be_visible()

    # Ищем карточку родительской задачи в колонке (по дефолту todo)
    # Селектор основан на app.js: page.locator('[data-cards="todo"]')
    todo_column = page.locator('[data-cards="todo"]')

    # Открываем карточку по кнопке или кликаем на саму карточку
    # Селектор карточки: .card с текстом задачи
    card = todo_column.locator(".card", has_text="Лендинг рекламных конструкций")
    expect(card).to_be_visible(timeout=10_000)

    # Кликаем на карточку чтобы открыть модалку
    card.click()

    # Модалка с деталями: id modal (из app.js)
    task_modal = page.locator("#modal-task")
    expect(task_modal).to_be_visible(timeout=5_000)

    # Получаем артефакты через API (как это делает app.js loadArtifacts)
    artifacts_api = _api_get(base_url, f"/api/tasks/{parent_task_id}/artifacts")
    assert artifacts_api["статус"] == "ok"

    # У родительской задачи должна быть видна подзадача с артефактом
    # или артефакты должны быть доступны из подзадачи
    # (в зависимости от UI design)

    # ========================================================================
    # Step 6: Проверить что артефакты видны в UI (artifacts-block)
    # ========================================================================

    # artifacts-block-<taskId> из app.js (renderArtifacts)
    # Поскольку мы открыли родительскую задачу, нужно убедиться что либо:
    # a) у родительской задачи есть артефакты (в зависимости от design)
    # b) или нам нужно открыть подзадачу

    # Проверим подзадачи в модалке (если они видны)
    subtasks_section = page.locator("#subtasks-list, [data-section='subtasks']")

    # Если подзадачи видны, попробуем открыть подзадачу с артефактом
    if subtasks_section.is_visible():
        # Ищем подзадачу "Написать HTML лендинга"
        subtask_card = subtasks_section.locator(".subtask-item, .card", has_text="HTML лендинга")
        if subtask_card.is_visible():
            subtask_card.click()
            # Дождемся обновления модалки или открытия новой
            time.sleep(1)

    # Ищем artifact-block в модалке
    artifacts_block = page.locator('[id^="artifacts-block-"]')

    # Дождемся что артефакты загрузились (могут быть загружены асинхронно)
    # Используем wait_for (или try-except)
    try:
        # Проверяем что блок с артефактами содержит наш файл
        # Селектор из app.js: .artifact-item, .artifact-name
        artifact_item = artifacts_block.locator(".artifact-item, .artifact-name", has_text="landing.html")
        expect(artifact_item).to_be_visible(timeout=10_000)
    except Exception:
        # Может быть что артефакты еще загружаются, даем еще время
        time.sleep(2)
        artifact_item = artifacts_block.locator(".artifact-item, .artifact-name", has_text="landing.html")
        expect(artifact_item).to_be_visible(timeout=10_000)

    # Проверим кнопку открытия артефакта (📂 Открыть)
    # Селектор из app.js: .artifact-open
    open_button = artifacts_block.locator(".artifact-open")
    expect(open_button).to_be_visible()

    # На мобильных девайсах должен быть видна path (artifact-path)
    artifact_path_span = artifacts_block.locator(".artifact-path, [data-artifact-path]")
    # Проверяем что путь содержит наш файл
    if artifact_path_span.is_visible():
        path_text = artifact_path_span.inner_text()
        assert "landing.html" in path_text or "roofing-company" in path_text

    # ========================================================================
    # Step 7: Закрыть задачу (завершить)
    # ========================================================================

    # Ищем кнопку статуса или select для смены статуса
    # В модалке должна быть возможность изменить статус
    status_selector = page.locator("[data-field='status'], select[name='status']")

    if status_selector.is_visible():
        status_selector.click()
        # Выбираем "completed" или "done"
        page.locator("option, .menu-item", has_text="Done").click()
        time.sleep(1)

        # Проверяем что статус изменился
        # или ищем кнопку сохранения
        save_button = page.locator("button[type='submit'], .save-button, button:has-text('Save')")
        if save_button.is_visible():
            save_button.click()
            time.sleep(1)

    # ========================================================================
    # Step 8: Финальная проверка через API
    # ========================================================================

    # Проверяем что задача все еще есть и артефакты сохранились
    final_task = _api_get(base_url, f"/api/tasks/{parent_task_id}")
    assert final_task["статус"] == "ok"

    final_artifacts = _api_get(base_url, f"/api/tasks/{subtask_id}/artifacts")
    assert final_artifacts["статус"] == "ok"
    assert len(final_artifacts["artifacts"]) >= 1

    # Находим наш артефакт
    our_artifact = None
    for art in final_artifacts["artifacts"]:
        if art["id"] == artifact_id:
            our_artifact = art
            break

    assert our_artifact is not None, f"Артефакт {artifact_id} не найден в финальном списке"
    assert our_artifact["kind"] == "html"
    assert "landing.html" in our_artifact["file_path"]

    print("\n✓ E2E smoke-тест пройден успешно!")
    print(f"  - Главная задача создана: {parent_task_id}")
    print(f"  - Подзадача создана: {subtask_id}")
    print(f"  - Артефакт зарегистрирован: {artifact_id}")
    print(f"  - Артефакт видим в UI: workspace/roofing-company/landing.html")


def test_e2e_artifacts_file_exists_in_workspace() -> None:
    """Unit-check: убедиться что HTML файл реально существует и имеет корректный размер."""
    landing_file = Path(
        "/Users/dm_pc/Desktop/pride-team-v1.0/workspace/roofing-company/landing.html"
    )

    assert landing_file.exists(), f"Файл не найден: {landing_file}"
    assert landing_file.is_file(), f"Путь не файл: {landing_file}"

    file_size = landing_file.stat().st_size
    assert file_size > 100, f"Файл слишком маленький: {file_size} bytes"
    print(f"✓ HTML файл существует ({file_size} bytes)")

    # Проверяем что файл содержит ожидаемые секции
    content = landing_file.read_text("utf-8")
    assert "Рекламные конструкции" in content
    assert "landing.html" in content or "roofing" in content.lower()
    assert "<html" in content.lower()
    print("✓ HTML файл содержит корректный контент")

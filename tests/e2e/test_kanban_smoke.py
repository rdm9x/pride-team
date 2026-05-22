"""E2E smoke на канбан-дашборд pride-team.

Покрываемые сценарии:
  1. test_create_task_via_ui — создание задачи через модалку «+ Новая задача»
     и проверка что карточка появилась в колонке `todo`.
  2. test_approve_needs_approval_flow — задача создаётся через API со
     status=needs_approval, открывается её модалка и нажимается кнопка
     «✓ Одобрить»; проверяем что статус сменился на `todo`.

Селекторы сверены с dashboard/templates/kanban.html и dashboard/static/app.js
по состоянию на 2026-05-21. Если фронтенд переименует id/data-атрибуты —
тесты упадут с понятной ошибкой про missing locator (это правильно).

Запуск:
    pip install -r requirements-dev.txt
    playwright install chromium
    pytest tests/e2e/ -v
    # headless по умолчанию; чтобы посмотреть глазами: --headed
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest
from playwright.sync_api import Page, expect

# Если по какой-то причине chromium не установлен — даём явный skip вместо
# падения внутри pytest-playwright. Это вторая линия защиты помимо conftest.
pytestmark = pytest.mark.e2e


def _api_post(base_url: str, path: str, body: dict) -> dict:
    """Короткий HTTP-POST помощник (stdlib, без зависимостей)."""
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


def test_create_task_via_ui(page: Page, base_url: str) -> None:
    """Юзер открывает дашборд, кликает «+ Новая задача», заполняет форму,
    submit'ит — карточка должна появиться в колонке `todo`.
    """
    page.goto(base_url)

    # Открываем доску — по дефолту активен Inbox, нужный data-view="board".
    page.locator('.nav-item[data-view="board"]').click()
    expect(page.locator('.view-board')).to_be_visible()

    # Кнопка «+ Новая задача» в топ-баре. id из шаблона.
    page.locator("#btn-new-task").click()

    # Модалка #modal-new с формой #form-new-task.
    modal = page.locator("#modal-new")
    expect(modal).to_be_visible()

    title = "E2E smoke: создание задачи через UI"
    description = "TL;DR: тест Playwright проверяет happy-path создания."
    modal.locator('input[name="title"]').fill(title)
    modal.locator('textarea[name="description"]').fill(description)
    # priority/assignee оставляем по умолчанию (P2 / тимлид) — этого достаточно.

    # Submit формы — кнопка типа submit внутри формы.
    modal.locator('button[type="submit"]').click()

    # После успешного создания app.js делает closeModal + refresh().
    expect(modal).to_be_hidden()

    # Карточка должна появиться в колонке data-cards="todo".
    todo_column = page.locator('[data-cards="todo"]')
    new_card = todo_column.locator(".card", has_text=title)
    expect(new_card).to_be_visible(timeout=5_000)

    # Контр-проверка: счётчик в шапке колонки todo == минимум 1.
    todo_count = page.locator('[data-count="todo"]')
    count_text = todo_count.inner_text().strip()
    assert count_text.isdigit() and int(count_text) >= 1, (
        f"data-count='todo' должен быть >=1, получили {count_text!r}"
    )


def test_approve_needs_approval_flow(page: Page, base_url: str) -> None:
    """Создаём задачу с status=needs_approval через API, открываем доску,
    кликаем на карточку, в модалке жмём «✓ Одобрить» — статус должен стать `todo`.
    """
    # 1. Через API создаём задачу прямо в нужном статусе.
    title = "E2E smoke: approval gate"
    created = _api_post(
        base_url,
        "/api/tasks",
        {
            "title": title,
            "description": "TL;DR: e2e на approval flow.",
            "status": "needs_approval",
            "assignee": "дмитрий",
            "reporter": "тимлид",
            "priority": "P1",
        },
    )
    assert created.get("статус") == "ok", f"API не создал задачу: {created}"
    task_id = created["задача"]["id"]

    # 2. Открываем дашборд → переключаемся на доску.
    page.goto(base_url)
    page.locator('.nav-item[data-view="board"]').click()
    expect(page.locator('.view-board')).to_be_visible()

    # 3. Карточка должна быть в колонке needs_approval.
    approval_column = page.locator('[data-cards="needs_approval"]')
    card = approval_column.locator(f'.card[data-id="{task_id}"]')
    expect(card).to_be_visible(timeout=5_000)

    # 4. Открываем модалку задачи и жмём «✓ Одобрить».
    card.click()
    modal = page.locator("#modal-task")
    expect(modal).to_be_visible()
    approve_btn = modal.locator('button.approve[data-action="approve"]')
    expect(approve_btn).to_be_visible()
    approve_btn.click()

    # 5. После approve app.js делает refresh + закрывает модалку.
    #    Проверяем что карточка переехала в колонку todo.
    todo_column = page.locator('[data-cards="todo"]')
    moved_card = todo_column.locator(f'.card[data-id="{task_id}"]')
    expect(moved_card).to_be_visible(timeout=5_000)

    # 6. И в колонке needs_approval её больше нет.
    expect(approval_column.locator(f'.card[data-id="{task_id}"]')).to_have_count(0)

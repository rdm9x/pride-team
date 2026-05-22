"""REST-тесты для endpoint /api/tasks/<id>/parsed (Task Reader Mode)."""

from __future__ import annotations


def test_parse_task_simple(client) -> None:
    """Тест парсинга простой задачи с TL;DR."""
    # Создаём задачу
    r = client.post(
        "/api/tasks",
        json={
            "title": "Фича",
            "description": "**TL;DR**: быстро сделать фичу\n\nДополнительные детали здесь",
        },
    )
    task_id = r.get_json()["задача"]["id"]

    # Получаем парсированную версию
    r = client.get(f"/api/tasks/{task_id}/parsed")
    assert r.status_code == 200
    data = r.get_json()
    assert data["статус"] == "ok"

    parsed = data["parsed"]
    assert parsed["tldr"] == "быстро сделать фичу"
    assert parsed["has_structure"] is True
    assert parsed["raw_markdown"] is not None


def test_parse_task_with_steps(client) -> None:
    """Тест парсинга задачи с шагами."""
    desc = """**TL;DR**: Новая фича

## Что делать

- Шаг 1: создать файл
- Шаг 2: добавить функцию
- Шаг 3: тесты"""

    r = client.post(
        "/api/tasks",
        json={"title": "Тест", "description": desc},
    )
    task_id = r.get_json()["задача"]["id"]

    r = client.get(f"/api/tasks/{task_id}/parsed")
    assert r.status_code == 200
    parsed = r.get_json()["parsed"]

    assert parsed["tldr"] == "Новая фича"
    assert parsed["steps"] is not None
    assert len(parsed["steps"]) == 3
    assert "Шаг 1" in parsed["steps"][0]
    assert parsed["has_structure"] is True


def test_parse_task_with_acceptance(client) -> None:
    """Тест парсинга задачи с acceptance criteria."""
    desc = """**TL;DR**: Проверка

## Acceptance

[ ] Критерий 1
[x] Критерий 2
[ ] Критерий 3"""

    r = client.post(
        "/api/tasks",
        json={"title": "Тест", "description": desc},
    )
    task_id = r.get_json()["задача"]["id"]

    r = client.get(f"/api/tasks/{task_id}/parsed")
    assert r.status_code == 200
    parsed = r.get_json()["parsed"]

    assert parsed["acceptance"] is not None
    assert len(parsed["acceptance"]) == 3
    assert parsed["acceptance"][0]["checked"] is False
    assert parsed["acceptance"][1]["checked"] is True
    assert parsed["acceptance"][2]["checked"] is False


def test_parse_task_with_options(client) -> None:
    """Тест парсинга задачи с вариантами ответов."""
    desc = """**TL;DR**: Выбирай

### Вариант реализации

- Вариант A
- Вариант B
- Вариант C"""

    r = client.post(
        "/api/tasks",
        json={"title": "Тест", "description": desc},
    )
    task_id = r.get_json()["задача"]["id"]

    r = client.get(f"/api/tasks/{task_id}/parsed")
    assert r.status_code == 200
    parsed = r.get_json()["parsed"]

    assert parsed["options"] is not None
    assert len(parsed["options"]) >= 3
    assert parsed["options"][0]["label"] == "Вариант A"


def test_parse_task_without_structure(client) -> None:
    """Тест парсинга задачи без структуры (fallback к raw markdown)."""
    desc = "Просто текст без всякой структуры и не имеет никаких заголовков"

    r = client.post(
        "/api/tasks",
        json={"title": "Тест", "description": desc},
    )
    task_id = r.get_json()["задача"]["id"]

    r = client.get(f"/api/tasks/{task_id}/parsed")
    assert r.status_code == 200
    parsed = r.get_json()["parsed"]

    assert parsed["tldr"] is None
    assert parsed["steps"] is None
    assert parsed["acceptance"] is None
    assert parsed["options"] is None
    assert parsed["has_structure"] is False


def test_parse_task_empty_description(client) -> None:
    """Тест парсинга задачи с пустым description."""
    r = client.post(
        "/api/tasks",
        json={"title": "Пустая задача", "description": ""},
    )
    task_id = r.get_json()["задача"]["id"]

    r = client.get(f"/api/tasks/{task_id}/parsed")
    assert r.status_code == 200
    parsed = r.get_json()["parsed"]

    assert parsed["has_structure"] is False
    assert parsed["raw_markdown"] == ""


def test_parse_task_not_found(client) -> None:
    """Тест парсинга несуществующей задачи."""
    r = client.get("/api/tasks/deadbeef/parsed")
    assert r.status_code == 404
    assert r.get_json()["статус"] == "not_found"


def test_parse_task_full_structured(client) -> None:
    """Интеграционный тест полностью структурированной задачи."""
    desc = """**TL;DR**: Реализовать двухслойное окно задачи

## Что делать

- Создать парсер
- Добавить endpoint
- Реализовать UI
- Написать тесты

## Acceptance

[ ] Парсер работает
[x] Tests pass
[ ] Документация

### Как реализовать?

- На JavaScript
- Через React
- С Vue"""

    r = client.post(
        "/api/tasks",
        json={"title": "S5.5", "description": desc},
    )
    task_id = r.get_json()["задача"]["id"]

    r = client.get(f"/api/tasks/{task_id}/parsed")
    assert r.status_code == 200
    parsed = r.get_json()["parsed"]

    # Проверяем все части
    assert parsed["tldr"] == "Реализовать двухслойное окно задачи"
    assert len(parsed["steps"]) == 4
    assert len(parsed["acceptance"]) == 3
    assert len(parsed["options"]) >= 3
    assert parsed["has_structure"] is True
    assert parsed["raw_markdown"] == desc


def test_parse_task_preserves_description_after_update(client) -> None:
    """Тест что парсинг работает после обновления description."""
    desc1 = "**TL;DR**: Первый текст"
    desc2 = "**TL;DR**: Второй текст\n\n## Что делать\n- Пункт 1"

    r = client.post(
        "/api/tasks",
        json={"title": "Тест", "description": desc1},
    )
    task_id = r.get_json()["задача"]["id"]

    # Проверяем первый парсинг
    r = client.get(f"/api/tasks/{task_id}/parsed")
    parsed = r.get_json()["parsed"]
    assert parsed["tldr"] == "Первый текст"
    assert parsed["steps"] is None

    # Обновляем задачу
    client.patch(f"/api/tasks/{task_id}", json={"description": desc2})

    # Проверяем второй парсинг
    r = client.get(f"/api/tasks/{task_id}/parsed")
    parsed = r.get_json()["parsed"]
    assert parsed["tldr"] == "Второй текст"
    assert parsed["steps"] is not None
    assert len(parsed["steps"]) == 1

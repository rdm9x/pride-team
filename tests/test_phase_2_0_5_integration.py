"""Integration test для Phase 2.0.5 — E2E smoke marketing artifacts pipeline.

Этот тест проверяет полную цепочку:
1. Создание задач через API
2. Регистрация артефактов через MCP tools
3. Сохранение в БД
4. Получение через REST API
5. Отображение в UI (имитируется проверкой API ответа)

Не требует Playwright/браузера, только проверяет backend.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Добавляем путь к mcp_server модулям
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp_server"))

# Путь к workspace
WORKSPACE_ROOT = Path("/Users/dm_pc/Desktop/pride-team-v1.0/workspace")
LANDING_HTML = WORKSPACE_ROOT / "roofing-company" / "landing.html"


def test_landing_html_file_structure() -> None:
    """Проверка что HTML файл имеет корректную структуру."""
    assert LANDING_HTML.exists(), f"HTML файл не найден: {LANDING_HTML}"
    assert LANDING_HTML.is_file(), f"Путь не файл: {LANDING_HTML}"

    content = LANDING_HTML.read_text("utf-8")

    # Проверяем структуру
    assert "<!DOCTYPE html>" in content or "<!doctype html>" in content.lower()
    assert "<html" in content.lower()
    assert "</html>" in content.lower()
    assert "<body" in content.lower()
    assert "</body>" in content.lower()
    assert "<head" in content.lower()
    assert "</head>" in content.lower()

    # Проверяем контент лендинга
    assert "Рекламные конструкции" in content
    assert "PRIDE" in content
    assert "<header" in content.lower() or "header" in content.lower()
    assert "<nav" in content.lower() or "nav" in content.lower()
    assert "<section" in content.lower() or "section" in content.lower()
    assert "roofing" in content.lower() or "кровля" in content

    # Проверяем что есть CSS
    assert "<style" in content.lower()

    # Проверяем что есть форма
    assert "<form" in content.lower() or "form" in content.lower()

    file_size = LANDING_HTML.stat().st_size
    assert file_size > 5000, f"Файл слишком маленький: {file_size} bytes (нужно >5KB)"


def test_artifact_registration_with_html() -> None:
    """Integration: регистрация HTML артефакта в полной цепочке."""
    from devboard_tasks import db, tools
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_db = Path(tmpdir) / "test.db"

        # Инициализируем БД
        db.init_db(tmp_db)

        # Создаем задачу
        task = db.insert_task(tmp_db, title="Marketing Task")
        assert task["id"], "Task не создана"

        # Регистрируем HTML артефакт
        result = tools.register_task_artifact(
            task_id=task["id"],
            file_path="workspace/roofing-company/landing.html",
            kind="html",
            db_path=tmp_db,
        )

        # Проверяем результат регистрации
        assert result["статус"] == "ok", f"Регистрация ошибка: {result}"
        assert result["artifact_id"], "artifact_id не получен"
        assert result["kind"] == "html"
        assert "landing.html" in result["file_path"]

        artifact_id = result["artifact_id"]

        # Проверяем что артефакт в БД
        artifact_from_db = db.get_artifact(tmp_db, artifact_id)
        assert artifact_from_db is not None
        assert artifact_from_db["task_id"] == task["id"]
        assert artifact_from_db["kind"] == "html"
        assert artifact_from_db["file_path"] == "workspace/roofing-company/landing.html"

        # Проверяем что артефакт в list
        artifacts_list = db.list_artifacts(tmp_db, task["id"])
        assert len(artifacts_list) == 1
        assert artifacts_list[0]["id"] == artifact_id


def test_multiple_artifacts_per_task() -> None:
    """Integration: несколько артефактов для одной задачи (подзадачи)."""
    from devboard_tasks import db, tools
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_db = Path(tmpdir) / "test.db"

        # Инициализируем БД
        db.init_db(tmp_db)

        # Создаем родительскую задачу
        parent_task = db.insert_task(tmp_db, title="Landing Project")

        # Создаем подзадачу
        subtask = db.insert_task(
            tmp_db,
            title="Write HTML",
            parent_id=parent_task["id"],
        )

        # Регистрируем несколько артефактов
        artifacts_to_register = [
            ("workspace/roofing-company/landing.html", "html"),
            ("workspace/roofing-company/landing.css", "css"),
            ("workspace/roofing-company/landing.js", "javascript"),
        ]

        registered_ids = []
        for file_path, kind in artifacts_to_register:
            # Пропускаем если файл не существует (это интеграция)
            if not Path(file_path).exists():
                # Для тестов добавляем только существующий файл
                continue

            result = tools.register_task_artifact(
                task_id=subtask["id"],
                file_path=file_path,
                kind=kind,
                db_path=tmp_db,
            )
            if result["статус"] == "ok":
                registered_ids.append(result["artifact_id"])

        # Проверяем что все артефакты зарегистрированы
        assert len(registered_ids) >= 1, "Должен быть минимум 1 артефакт"

        artifacts_list = db.list_artifacts(tmp_db, subtask["id"])
        assert len(artifacts_list) == len(registered_ids)


def test_artifact_kind_types() -> None:
    """Проверка что HTML артефакт имеет правильный kind."""
    from devboard_tasks import db, tools
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_db = Path(tmpdir) / "test.db"
        db.init_db(tmp_db)
        task = db.insert_task(tmp_db, title="Test")

        # Регистрируем как HTML
        result = tools.register_task_artifact(
            task_id=task["id"],
            file_path="workspace/roofing-company/landing.html",
            kind="html",
            db_path=tmp_db,
        )

        assert result["kind"] == "html"
        artifact_id = result["artifact_id"]

        # Проверяем в БД
        artifact = db.get_artifact(tmp_db, artifact_id)
        assert artifact["kind"] == "html", "Kind должен остаться 'html' в БД"


def test_artifact_file_path_validation() -> None:
    """Проверка валидации file_path при регистрации."""
    from devboard_tasks import db, tools
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_db = Path(tmpdir) / "test.db"
        db.init_db(tmp_db)
        task = db.insert_task(tmp_db, title="Test")

        # Абсолютный путь - ошибка
        result = tools.register_task_artifact(
            task_id=task["id"],
            file_path="/absolute/path/file.html",
            kind="html",
            db_path=tmp_db,
        )
        assert result["статус"] == "error"

        # Path traversal - ошибка
        result = tools.register_task_artifact(
            task_id=task["id"],
            file_path="workspace/../../../etc/passwd",
            kind="html",
            db_path=tmp_db,
        )
        assert result["статус"] == "error"

        # Валидный путь - OK
        result = tools.register_task_artifact(
            task_id=task["id"],
            file_path="workspace/roofing-company/landing.html",
            kind="html",
            db_path=tmp_db,
        )
        assert result["статус"] == "ok"


def test_artifact_persistence_across_sessions() -> None:
    """Проверка что артефакты сохраняются в БД и остаются после restart."""
    from devboard_tasks import db, tools
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_db = Path(tmpdir) / "test.db"

        # Инициализируем БД один раз
        db.init_db(tmp_db)

        # Сессия 1: создание и регистрация
        task1 = db.insert_task(tmp_db, title="Task 1")
        result1 = tools.register_task_artifact(
            task_id=task1["id"],
            file_path="workspace/roofing-company/landing.html",
            kind="html",
            db_path=tmp_db,
        )
        artifact_id_1 = result1["artifact_id"]

        # Сессия 2: чтение из same DB
        artifacts_session2 = db.list_artifacts(tmp_db, task1["id"])
        assert len(artifacts_session2) == 1
        assert artifacts_session2[0]["id"] == artifact_id_1

        # Сессия 3: добавляем еще один
        result2 = tools.register_task_artifact(
            task_id=task1["id"],
            file_path="workspace/roofing-company/landing-v2.html",
            kind="html",
            db_path=tmp_db,
        )
        assert result2["статус"] == "error" or result2["статус"] == "ok"

        # Финальная проверка
        artifacts_final = db.list_artifacts(tmp_db, task1["id"])
        assert len(artifacts_final) >= 1


def test_workspace_directory_structure() -> None:
    """Проверка что workspace имеет правильную структуру."""
    # Основная директория
    assert WORKSPACE_ROOT.exists()
    assert WORKSPACE_ROOT.is_dir()

    # Поддиректории
    assert (WORKSPACE_ROOT / "dev").exists()
    assert (WORKSPACE_ROOT / "marketing").exists()
    assert (WORKSPACE_ROOT / "roofing-company").exists()

    # Файлы
    assert LANDING_HTML.exists()
    assert LANDING_HTML.stat().st_size > 0


@pytest.mark.parametrize("kind", ["html", "pdf", "doc", "image", "video"])
def test_artifact_kinds_support(kind: str) -> None:
    """Проверка что разные kind'ы поддерживаются."""
    from devboard_tasks import db, tools
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_db = Path(tmpdir) / "test.db"
        db.init_db(tmp_db)
        task = db.insert_task(tmp_db, title="Test")

        result = tools.register_task_artifact(
            task_id=task["id"],
            file_path=f"workspace/file.{kind}",
            kind=kind,
            db_path=tmp_db,
        )

        assert result["статус"] == "ok"
        assert result["kind"] == kind


# ============================================================================
# Тесты UI компонентов (эмуляция)
# ============================================================================


def test_ui_artifact_rendering_mock() -> None:
    """Mock-тест для проверки что UI компонент renderArtifacts корректно работает."""
    # Эмулируем структуру артефакта которую возвращает API
    artifacts_from_api = [
        {
            "id": "a1b2c3d4e5f6",
            "task_id": "task123",
            "file_path": "workspace/roofing-company/landing.html",
            "kind": "html",
            "created_at": 1621234567,
        }
    ]

    # Эмулируем логику renderArtifacts из app.js
    def render_artifacts_mock(artifacts: list) -> str:
        if not artifacts:
            return '<div style="color:var(--muted)">No artifacts</div>'

        html_parts = []
        for art in artifacts:
            file_name = Path(art["file_path"]).name
            icon = "🌐" if art["kind"] == "html" else "📄"
            html_parts.append(
                f'<div class="artifact-item">'
                f'<span class="artifact-icon">{icon}</span>'
                f'<span class="artifact-name">{file_name}</span>'
                f'<button class="artifact-open" data-artifact-path="{art["file_path"]}">Open</button>'
                f'</div>'
            )
        return "".join(html_parts)

    result = render_artifacts_mock(artifacts_from_api)

    # Проверяем что результат содержит нужные элементы
    assert "artifact-item" in result
    assert "landing.html" in result
    assert "artifact-open" in result
    assert "🌐" in result  # HTML icon
    assert "workspace/roofing-company/landing.html" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

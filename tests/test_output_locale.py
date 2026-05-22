"""Тесты S2.2 — backend часть: сохранение output_locale через POST /api/team/start.

Покрытие:
* output_locale=en → .output_locale содержит "en"
* Без output_locale → .output_locale содержит "ru" (дефолт)
* output_locale=de (неизвестный) → .output_locale содержит "ru" (fallback)

Locale-файл пишется рядом с DB: _db().parent / ".output_locale".
В тестах DB в tmp_path, значит locale → tmp_path/.output_locale.
В проде DB в data/, значит locale → data/.output_locale — именно то,
что читает commands/devboard-work.sh.

Запуск: pytest tests/test_output_locale.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Убеждаемся что dashboard/ и mcp_server/ в sys.path
_ROOT = Path(__file__).resolve().parents[1]
_DASHBOARD = _ROOT / "dashboard"
_MCP = _ROOT / "mcp_server"
for _p in (_DASHBOARD, _MCP):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


@pytest.fixture()
def client(tmp_path: Path):
    """Flask test client с изолированной базой во tmp_path.

    Locale-файл будет записан в tmp_path/.output_locale,
    т.к. _db().parent == tmp_path в тестах.
    """
    from app import create_app  # type: ignore[import-not-found]

    db_path = tmp_path / "tasks.db"
    app = create_app(db_path=db_path)
    app.config["TESTING"] = True

    with app.test_client() as c:
        yield c, tmp_path


def test_output_locale_saved_on_start(client):
    """POST /api/team/start с output_locale=en → .output_locale содержит "en"."""
    flask_client, data_dir = client
    locale_file = data_dir / ".output_locale"

    resp = flask_client.post(
        "/api/team/start",
        json={"output_locale": "en"},
        content_type="application/json",
    )
    # Endpoint может вернуть 409 если скрипт не найден, но файл должен быть записан ДО запуска.
    assert resp.status_code in (200, 409)
    assert locale_file.exists(), "файл .output_locale должен быть создан"
    assert locale_file.read_text().strip() == "en"


def test_output_locale_default_ru(client):
    """POST /api/team/start без output_locale → .output_locale содержит "ru"."""
    flask_client, data_dir = client
    locale_file = data_dir / ".output_locale"

    resp = flask_client.post(
        "/api/team/start",
        json={},
        content_type="application/json",
    )
    assert resp.status_code in (200, 409)
    assert locale_file.exists(), "файл .output_locale должен быть создан"
    assert locale_file.read_text().strip() == "ru"


def test_output_locale_invalid_falls_back_to_ru(client):
    """output_locale="de" → .output_locale содержит "ru" (только ru/en разрешены)."""
    flask_client, data_dir = client
    locale_file = data_dir / ".output_locale"

    resp = flask_client.post(
        "/api/team/start",
        json={"output_locale": "de"},
        content_type="application/json",
    )
    assert resp.status_code in (200, 409)
    assert locale_file.exists(), "файл .output_locale должен быть создан"
    assert locale_file.read_text().strip() == "ru"

"""Фикстуры для e2e-тестов pride-team.

Поднимаем настоящий Flask-дашборд (`dashboard/app.py`) в фоновом потоке
поверх временного SQLite. Тесты ходят по реальному HTTP через Playwright —
никаких моков, никаких подмен Werkzeug.

Запуск:
    pip install -r requirements-dev.txt
    playwright install chromium
    pytest tests/e2e/ -v

Если на стенде нет playwright — все тесты будут skipped (см. pytest.importorskip).
Если нет браузера — pytest-playwright выдаст internal-ошибку, и в этом случае
читай комментарий: `playwright install chromium`.
"""

from __future__ import annotations

import socket
import sys
import threading
import time
from pathlib import Path

import pytest

# Делаем дашборд импортируемым из любого места проекта.
_ROOT = Path(__file__).resolve().parents[2]
_DASHBOARD = _ROOT / "dashboard"
if str(_DASHBOARD) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD))

# Если playwright не установлен — даём pytest корректно skip'нуть все тесты
# вместо collection-error'а.
pytest.importorskip(
    "playwright.sync_api",
    reason="playwright не установлен. `pip install pytest-playwright && playwright install chromium`",
)


def _free_port() -> int:
    """Берём свободный TCP-порт у ОС."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_until_up(host: str, port: int, timeout: float = 10.0) -> None:
    """Ждём пока Flask поднимется и начнёт принимать соединения."""
    deadline = time.time() + timeout
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError as exc:
            last_err = exc
            time.sleep(0.1)
    raise RuntimeError(f"Flask на {host}:{port} не поднялся за {timeout}с (last: {last_err})")


@pytest.fixture(scope="session")
def live_server(tmp_path_factory: pytest.TempPathFactory) -> str:
    """Стартует Flask-дашборд в фоновом daemon-потоке на свободном порту.

    Возвращает базовый URL вида `http://127.0.0.1:<port>`.
    БД — временный sqlite в tmp_path_factory, чтобы не сорить в data/.
    """
    from app import create_app  # type: ignore[import-not-found]

    db_path = tmp_path_factory.mktemp("e2e-db") / "tasks.db"
    app = create_app(db_path=db_path)
    app.config["TESTING"] = True

    host = "127.0.0.1"
    port = _free_port()

    def _run() -> None:
        # use_reloader=False — иначе Flask форкнёт второй процесс и сломает поток.
        app.run(host=host, port=port, debug=False, threaded=True, use_reloader=False)

    thread = threading.Thread(target=_run, daemon=True, name=f"e2e-flask-{port}")
    thread.start()
    _wait_until_up(host, port)
    base_url = f"http://{host}:{port}"
    yield base_url
    # Демон-поток умрёт вместе с pytest — явное shutdown через werkzeug
    # требует request-context, и для e2e-сюиты overkill.


@pytest.fixture()
def base_url(live_server: str) -> str:
    """Алиас для удобства — каждый тест получает чистый URL."""
    return live_server

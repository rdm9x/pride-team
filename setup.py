"""Кросс-платформенный установщик devboard.

Запуск:
    python setup.py            (или python3 setup.py)

Что делает:
  1. Проверяет Python >= 3.11.
  2. Устанавливает uv если его нет (через pip).
  3. Создаёт venv'ы для mcp_server и dashboard, ставит зависимости.
  4. Генерирует .mcp.json с правильными абсолютными путями под текущую машину.
  5. Прогоняет тесты обоих подпроектов (67 шт).
  6. Печатает инструкцию как запустить.

Безопасно для повторного запуска: venv'ы пересоздаются, .mcp.json
перезаписывается. БД канбана (data/tasks.db) НЕ трогается.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IS_WINDOWS = sys.platform == "win32"


def log(msg: str, kind: str = "info") -> None:
    marker = {"info": "·", "ok": "✓", "warn": "!", "err": "✗"}.get(kind, "·")
    print(f"{marker} {msg}", flush=True)


def fail(msg: str) -> "Never":  # type: ignore[name-defined]
    log(msg, "err")
    sys.exit(1)


def run(cmd: list[str], cwd: Path | None = None, env: dict | None = None) -> None:
    log("$ " + " ".join(str(c) for c in cmd))
    result = subprocess.run(cmd, cwd=cwd, env=env or os.environ.copy())
    if result.returncode != 0:
        fail(f"команда упала с кодом {result.returncode}")


def check_python() -> None:
    if sys.version_info < (3, 11):
        fail(
            f"Нужен Python >= 3.11, у вас {sys.version_info.major}.{sys.version_info.minor}. "
            "Поставьте Python 3.11+ с https://www.python.org/downloads/ и перезапустите."
        )
    log(f"Python {sys.version.split()[0]} ({platform.system()} {platform.machine()})", "ok")


def ensure_uv() -> str:
    """Возвращает путь к uv. Ставит через pip если нет."""
    uv = shutil.which("uv")
    if uv:
        log(f"uv уже установлен: {uv}", "ok")
        return uv
    log("uv не найден, ставлю через pip...", "warn")
    run([sys.executable, "-m", "pip", "install", "--user", "uv"])
    # После --user исполняемые скрипты лежат в user-base
    user_base = subprocess.check_output(
        [sys.executable, "-c", "import site, sys; sys.stdout.write(site.USER_BASE)"],
        text=True,
    ).strip()
    candidates = [
        Path(user_base) / "Scripts" / ("uv.exe" if IS_WINDOWS else "uv"),
        Path(user_base) / "bin" / ("uv.exe" if IS_WINDOWS else "uv"),
    ]
    for cand in candidates:
        if cand.exists():
            log(f"uv поставлен: {cand}", "ok")
            return str(cand)
    fail("uv не нашёлся после установки. Перезапустите терминал и запустите setup.py снова.")


def setup_venv(uv: str, project_dir: Path, extras: str | None = None) -> Path:
    """Создаёт venv в project_dir/.venv через uv и ставит проект editable."""
    log(f"Настраиваю venv: {project_dir.name}", "info")
    # uv venv создаёт .venv в текущем каталоге
    run([uv, "venv", "--allow-existing"], cwd=project_dir)
    target = f".[{extras}]" if extras else "."
    run([uv, "pip", "install", "-e", target], cwd=project_dir)
    # Бинарь python в venv
    venv_python = (
        project_dir / ".venv" / "Scripts" / "python.exe"
        if IS_WINDOWS
        else project_dir / ".venv" / "bin" / "python"
    )
    if not venv_python.exists():
        fail(f"venv python не найден: {venv_python}")
    log(f"  python: {venv_python}", "ok")
    return venv_python


def setup_dashboard_extras(uv: str, project_dir: Path) -> Path:
    """Дашборд — отдельно ставим pytest + flask (через pip)."""
    run([uv, "pip", "install", "pytest", "flask"], cwd=project_dir)
    venv_python = (
        project_dir / ".venv" / "Scripts" / "python.exe"
        if IS_WINDOWS
        else project_dir / ".venv" / "bin" / "python"
    )
    return venv_python


def write_mcp_json() -> None:
    """Генерирует .mcp.json с абсолютными путями под текущую машину."""
    mcp_venv = ROOT / "mcp_server" / ".venv"
    python_path = (
        mcp_venv / "Scripts" / "python.exe" if IS_WINDOWS else mcp_venv / "bin" / "python"
    )
    config = {
        "mcpServers": {
            "pride-tasks": {
                "type": "stdio",
                "command": str(python_path),
                "args": ["-m", "pride_tasks"],
                "env": {
                    "PRIDE_TASKS_DB": str(ROOT / "data" / "tasks.db"),
                    "PYTHONPATH": str(ROOT / "mcp_server"),
                },
            }
        }
    }
    out = ROOT / ".mcp.json"
    out.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f".mcp.json сгенерирован: {out}", "ok")


def run_tests(mcp_python: Path, dash_python: Path) -> None:
    log("Прогон тестов MCP-сервера (51 шт)...", "info")
    run([str(mcp_python), "-m", "pytest", "mcp_server/tests/", "-q"], cwd=ROOT)
    log("Прогон тестов дашборда (16 шт)...", "info")
    run([str(dash_python), "-m", "pytest", "dashboard/tests/", "-q"], cwd=ROOT)
    log("Все 67 тестов зелёные", "ok")


def print_final_instructions() -> None:
    print()
    log("Установка завершена.", "ok")
    print()
    if IS_WINDOWS:
        print("  Запуск дашборда:")
        print("    powershell -ExecutionPolicy Bypass -File commands\\devboard-start.ps1")
        print()
        print("  Открыть в браузере:  http://127.0.0.1:5000")
        print()
        print("  Остановить:")
        print("    powershell -ExecutionPolicy Bypass -File commands\\devboard-stop.ps1")
    else:
        print("  Запуск дашборда:    ./commands/devboard-start.sh")
        print("  Открыть в браузере: http://127.0.0.1:5000")
        print("  Остановить:         ./commands/devboard-stop.sh")
    print()
    print("  Подробнее — README.md")
    print()


def main() -> None:
    print()
    log(f"devboard setup · {ROOT}")
    print()
    check_python()
    uv = ensure_uv()
    mcp_python = setup_venv(uv, ROOT / "mcp_server", extras="dev")
    setup_venv(uv, ROOT / "dashboard")
    dash_python = setup_dashboard_extras(uv, ROOT / "dashboard")
    write_mcp_json()
    (ROOT / "data").mkdir(exist_ok=True)
    run_tests(mcp_python, dash_python)
    print_final_instructions()


if __name__ == "__main__":
    main()

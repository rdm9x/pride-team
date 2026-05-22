"""Тесты для user_expertise (задача S3.4)."""

from __future__ import annotations

from pathlib import Path


def test_start_saves_user_expertise_non_tech(client, tmp_path, monkeypatch) -> None:
    """POST /api/team/start с user_expertise=non-tech сохраняет файл .user_expertise."""
    import app as dashboard_app  # type: ignore

    # Подменяем _COMMANDS_DIR на tmp_path и создаём фиктивный скрипт
    fake_script = tmp_path / "devboard-work.sh"
    fake_script.write_text("#!/bin/bash\necho 'ok'\n")
    fake_script.chmod(0o755)
    monkeypatch.setattr(dashboard_app, "_COMMANDS_DIR", tmp_path)

    r = client.post(
        "/api/team/start",
        json={"user_expertise": "non-tech"},
    )
    # Может вернуть ok (если процесс запустился) или 409 (already_running / missing_script)
    # Нас интересует только что файл записан корректно.
    db_path: Path = client.application.config["DB_PATH"]
    expertise_file = db_path.parent / ".user_expertise"
    assert expertise_file.exists(), ".user_expertise не был создан"
    assert expertise_file.read_text().strip() == "non-tech"


def test_start_saves_user_expertise_tech(client, tmp_path, monkeypatch) -> None:
    """POST /api/team/start с user_expertise=tech сохраняет 'tech'."""
    import app as dashboard_app  # type: ignore

    fake_script = tmp_path / "devboard-work.sh"
    fake_script.write_text("#!/bin/bash\necho 'ok'\n")
    fake_script.chmod(0o755)
    monkeypatch.setattr(dashboard_app, "_COMMANDS_DIR", tmp_path)

    client.post("/api/team/start", json={"user_expertise": "tech"})

    db_path: Path = client.application.config["DB_PATH"]
    expertise_file = db_path.parent / ".user_expertise"
    assert expertise_file.exists()
    assert expertise_file.read_text().strip() == "tech"


def test_start_defaults_to_non_tech(client, tmp_path, monkeypatch) -> None:
    """POST /api/team/start без user_expertise → дефолт non-tech."""
    import app as dashboard_app  # type: ignore

    fake_script = tmp_path / "devboard-work.sh"
    fake_script.write_text("#!/bin/bash\necho 'ok'\n")
    fake_script.chmod(0o755)
    monkeypatch.setattr(dashboard_app, "_COMMANDS_DIR", tmp_path)

    client.post("/api/team/start", json={})

    db_path: Path = client.application.config["DB_PATH"]
    expertise_file = db_path.parent / ".user_expertise"
    assert expertise_file.exists()
    assert expertise_file.read_text().strip() == "non-tech"


def test_start_rejects_unknown_expertise(client, tmp_path, monkeypatch) -> None:
    """POST /api/team/start с неизвестным user_expertise → fallback non-tech."""
    import app as dashboard_app  # type: ignore

    fake_script = tmp_path / "devboard-work.sh"
    fake_script.write_text("#!/bin/bash\necho 'ok'\n")
    fake_script.chmod(0o755)
    monkeypatch.setattr(dashboard_app, "_COMMANDS_DIR", tmp_path)

    client.post("/api/team/start", json={"user_expertise": "guru"})

    db_path: Path = client.application.config["DB_PATH"]
    expertise_file = db_path.parent / ".user_expertise"
    assert expertise_file.exists()
    assert expertise_file.read_text().strip() == "non-tech"


def test_devboard_work_sh_reads_expertise() -> None:
    """devboard-work.sh содержит код чтения .user_expertise и блок non-tech промта."""
    import re
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "commands" / "devboard-work.sh"
    assert script.exists(), "devboard-work.sh не найден"
    content = script.read_text(encoding="utf-8")

    # Скрипт читает .user_expertise
    assert ".user_expertise" in content, "Скрипт не читает .user_expertise"
    # Скрипт передаёт non-tech prompt через --append-system-prompt
    assert "non-technical" in content, "Блок non-tech промта не найден в скрипте"
    # Скрипт экспортирует DEVBOARD_USER_EXPERTISE
    assert "DEVBOARD_USER_EXPERTISE" in content, "DEVBOARD_USER_EXPERTISE не найден в скрипте"
    # non-tech ветка использует --append-system-prompt с expertise prompt
    assert re.search(r'append-system-prompt.*EXPERTISE_PROMPT|EXPERTISE_PROMPT.*append-system-prompt',
                     content, re.DOTALL), "EXPERTISE_PROMPT не передаётся через --append-system-prompt"

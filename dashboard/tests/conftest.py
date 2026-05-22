"""Фикстуры тестов дашборда."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Добавляем родителя в sys.path чтобы импортировать app.py
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture()
def client(tmp_path: Path):
    from app import create_app  # type: ignore

    db = tmp_path / "tasks.db"
    app = create_app(db_path=db)
    app.config["TESTING"] = True
    return app.test_client()

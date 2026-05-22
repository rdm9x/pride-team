"""Тесты для smoke/hello.py."""

import sys
from pathlib import Path

# Чтобы тесты находили модуль hello.py при запуске из /D.AI/команда/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hello import greet  # noqa: E402


def test_greet_happy_path():
    """Обычный кейс: имя подставляется в шаблон."""
    assert greet("пользователь") == "Привет, пользователь!"


def test_greet_empty_string():
    """Edge-case: пустая строка возвращает "Привет, !" — задокументированное поведение."""
    assert greet("") == "Привет, !"


def test_greet_unicode():
    """Доп. кейс: эмодзи и неаскии не ломают форматирование."""
    assert greet("Мир 🌍") == "Привет, Мир 🌍!"

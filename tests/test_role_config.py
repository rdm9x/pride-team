"""Тесты E6.6: LLM-конфиг в frontmatter roles/*.md.

Acceptance из задачи E6.6:
  * Все 7 файлов ролей имеют `llm`, `model`, `name`, `description` в frontmatter.
  * `validate_role_file` возвращает ok=True для каждого файла.
  * `create_provider(role_config)` не падает для каждого файла.
  * Смена провайдера = изменение 1 строки `llm:` в roles/*.md.

Запуск: `python -m pytest tests/test_role_config.py -v`
"""

from __future__ import annotations

from pathlib import Path

import pytest

from llm.factory import create_provider
from roles.validator import validate_role_file

REPO_ROOT = Path(__file__).resolve().parent.parent
ROLES_DIR = REPO_ROOT / "roles"

# Исчерпывающий список 7 файлов ролей с ожидаемыми slug-именами.
ROLE_FILES = [
    ("dev/lead.md", "dev-lead"),
    ("бэкенд.md", "backend"),
    ("qa.md", "qa"),
    ("архитектор.md", "architect"),
    ("frontend.md", "frontend"),
    ("devops.md", "devops"),
    ("техписатель.md", "techwriter"),
]


# ---------------------------------------------------------------------------
# Параметризованные тесты — один вызов на файл
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("filename,expected_name", ROLE_FILES)
def test_role_file_validates_ok(filename: str, expected_name: str) -> None:
    """Каждый из 7 файлов ролей должен пройти strict-валидацию ADR-002."""
    path = ROLES_DIR / filename
    result = validate_role_file(path)
    assert result.ok, (
        f"{filename}: валидация провалилась — {result.errors}"
    )


@pytest.mark.parametrize("filename,expected_name", ROLE_FILES)
def test_role_file_has_required_llm_fields(filename: str, expected_name: str) -> None:
    """Каждый файл роли содержит обязательные поля: llm, model, name, description."""
    path = ROLES_DIR / filename
    result = validate_role_file(path)
    assert result.config is not None, (
        f"{filename}: config=None, ошибки: {result.errors}"
    )
    cfg = result.config

    assert cfg.llm in ("claude", "openai", "ollama"), (
        f"{filename}: поле 'llm' должно быть claude/openai/ollama, получили {cfg.llm!r}"
    )
    assert cfg.model, (
        f"{filename}: поле 'model' пустое или отсутствует"
    )
    assert cfg.name == expected_name, (
        f"{filename}: ожидали name={expected_name!r}, получили {cfg.name!r}"
    )
    assert cfg.description, (
        f"{filename}: поле 'description' пустое или отсутствует"
    )
    assert len(cfg.description) <= 100, (
        f"{filename}: description длиннее 100 символов ({len(cfg.description)})"
    )


@pytest.mark.parametrize("filename,expected_name", ROLE_FILES)
def test_create_provider_from_role_config(filename: str, expected_name: str) -> None:
    """create_provider(role_config) не падает для каждого из 7 файлов ролей.

    Проверяет что фабрика умеет строить провайдер по конфигу из frontmatter.
    Для claude — строится ClaudeCLIProvider (не делает сетевых вызовов).
    Для openai/ollama — аналогично; если llm не claude, тест помечается
    xfail-skip только если требуется реальный env-ключ, но в данном случае
    все роли используют llm: claude, поэтому все зелёные.
    """
    path = ROLES_DIR / filename
    result = validate_role_file(path)
    assert result.config is not None, (
        f"{filename}: config не распарсился, ошибки: {result.errors}"
    )

    # Собираем минимальный config-dict из полей RoleConfig для factory.
    cfg = result.config
    config_dict: dict = {
        "llm": cfg.llm,
        "model": cfg.model,
    }
    if cfg.extras:
        config_dict["extras"] = cfg.extras

    # create_provider не должен бросать исключений при конструировании.
    provider = create_provider(config_dict)
    assert provider is not None, (
        f"{filename}: create_provider вернул None"
    )
    # Модель должна совпадать с тем что записано в frontmatter.
    assert provider.model == cfg.model, (
        f"{filename}: ожидали model={cfg.model!r}, провайдер сообщил {provider.model!r}"
    )


# ---------------------------------------------------------------------------
# Дополнительные проверки — schema_version и tools
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("filename,expected_name", ROLE_FILES)
def test_role_file_schema_version_is_1(filename: str, expected_name: str) -> None:
    """schema_version должна быть равна 1 у всех файлов после E6.6."""
    path = ROLES_DIR / filename
    result = validate_role_file(path)
    assert result.config is not None
    assert result.config.schema_version == 1, (
        f"{filename}: schema_version={result.config.schema_version!r}, ожидали 1"
    )


@pytest.mark.parametrize("filename,expected_name", ROLE_FILES)
def test_role_file_model_is_opus(filename: str, expected_name: str) -> None:
    """Все роли по умолчанию используют claude-opus-4-7 (E6.6 spec)."""
    path = ROLES_DIR / filename
    result = validate_role_file(path)
    assert result.config is not None
    assert result.config.model == "claude-opus-4-7", (
        f"{filename}: model={result.config.model!r}, ожидали claude-opus-4-7"
    )

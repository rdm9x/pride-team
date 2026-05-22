"""Тесты `roles.validator` — валидатора формата ролей (ADR-002).

Покрытие:
* Валидный файл → ok=True, config заполнен, body_length > 0.
* Missing required field (`name`) → ok=False с понятной ошибкой.
* Oversize (>50KB) → ok=False с упоминанием лимита.
* Wrong enum для `llm` → ok=False с перечислением допустимых значений.
* Невалидный slug в `name` (заглавные / пробелы / underscore) → ok=False.
* Пустое тело → ok=False.
* Невалидный YAML → ok=False.
* Отсутствие frontmatter вовсе → ok=False.
* validate_all() возвращает словарь по всем `*.md` в директории.
* CLI-режим: exit 0 при всех OK, exit 1 при хотя бы одном FAIL.
* Существующие 7 файлов `roles/*.md` — known limitation (legacy формат),
  проверяем что валидатор НЕ крэшится и собирает ошибки структурно.

Запуск: `python -m pytest tests/test_role_validator.py -v`.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from roles.validator import (
    MAX_ROLE_FILE_SIZE,
    RoleConfig,
    RoleConfigError,
    ValidationResult,
    main as validator_main,
    validate_all,
    validate_role_file,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
EXISTING_ROLES_DIR = REPO_ROOT / "roles"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


VALID_FRONTMATTER = """---
schema_version: 1
name: backend
description: Python backend dev — writes code, tests, configs.
llm: claude
model: claude-sonnet-4-5
temperature: 0.3
max_tokens: 8192
---
# You are a backend developer

This is the body of the system prompt for the backend role.
It must be at least 10 characters non-whitespace to pass validation.
"""


# ---------------------------------------------------------------------------
# Базовый happy-path
# ---------------------------------------------------------------------------


def test_valid_role_file(tmp_path: Path) -> None:
    p = _write(tmp_path / "backend.md", VALID_FRONTMATTER)
    result = validate_role_file(p)

    assert result.ok is True, f"unexpected errors: {result.errors}"
    assert result.errors == []
    assert result.config is not None
    assert result.config.name == "backend"
    assert result.config.llm == "claude"
    assert result.config.model == "claude-sonnet-4-5"
    assert result.config.schema_version == 1
    assert result.body_length > 10


def test_valid_with_extras_and_legacy(tmp_path: Path) -> None:
    """Legacy-поля (`тип`, `проект`) и `extras` сохраняются (ADR-002 §2.6)."""
    content = """---
schema_version: 1
name: qa-lead
description: QA engineer for pride-team.
llm: openai
model: gpt-4o
tools:
  - Read
  - Bash
extras:
  custom_flag: true
тип: системный_промт_роли
роль: qa
---
# QA role body
something useful here.
"""
    p = _write(tmp_path / "qa.md", content)
    result = validate_role_file(p)

    assert result.ok, f"errors: {result.errors}"
    assert result.config.name == "qa-lead"
    assert result.config.tools == ["Read", "Bash"]
    assert result.config.extras == {"custom_flag": True}
    # Legacy-поля попадают в model_extra благодаря extra=allow.
    assert "тип" in (result.config.model_extra or {})


def test_default_optional_fields(tmp_path: Path) -> None:
    """Опциональные поля принимают дефолты из ADR-002 §2.3."""
    content = """---
schema_version: 1
name: minimal
description: minimal role
llm: ollama
model: llama3.1
---
This is the role body — long enough.
"""
    p = _write(tmp_path / "minimal.md", content)
    result = validate_role_file(p)

    assert result.ok, result.errors
    cfg = result.config
    assert cfg.tools == "*"
    assert cfg.temperature == 0.3
    assert cfg.max_tokens == 8192
    assert cfg.extras == {}


# ---------------------------------------------------------------------------
# Negative-cases
# ---------------------------------------------------------------------------


def test_missing_required_field_name(tmp_path: Path) -> None:
    content = """---
schema_version: 1
description: role without a name
llm: claude
model: claude-sonnet-4-5
---
body here is long enough
"""
    p = _write(tmp_path / "broken.md", content)
    result = validate_role_file(p)

    assert result.ok is False
    assert any("'name'" in e and "required" in e for e in result.errors), \
        f"expected 'name is required' error, got {result.errors}"


def test_missing_required_field_llm(tmp_path: Path) -> None:
    content = """---
schema_version: 1
name: foo
description: role without llm
model: claude-sonnet-4-5
---
body here is long enough
"""
    p = _write(tmp_path / "broken.md", content)
    result = validate_role_file(p)

    assert result.ok is False
    assert any("'llm'" in e and "required" in e for e in result.errors), \
        f"expected 'llm is required' error, got {result.errors}"


def test_oversize_file(tmp_path: Path) -> None:
    # Делаем файл явно >50KB: 51 KB строкой.
    big_body = "x" * (51 * 1024)
    content = VALID_FRONTMATTER + big_body
    p = _write(tmp_path / "huge.md", content)

    assert p.stat().st_size > MAX_ROLE_FILE_SIZE

    result = validate_role_file(p)
    assert result.ok is False
    assert any("50KB" in e or "exceeds" in e for e in result.errors), \
        f"expected 50KB limit error, got {result.errors}"


def test_wrong_llm_enum(tmp_path: Path) -> None:
    content = """---
schema_version: 1
name: foo
description: bad llm
llm: gpt5-bogus
model: whatever
---
body here is long enough
"""
    p = _write(tmp_path / "bad-llm.md", content)
    result = validate_role_file(p)

    assert result.ok is False
    joined = " | ".join(result.errors).lower()
    # Acceptance: «field 'llm' must be one of: claude, openai, ollama».
    assert "llm" in joined
    assert "claude" in joined and "openai" in joined and "ollama" in joined


@pytest.mark.parametrize(
    "bad_name",
    [
        "Backend",       # заглавные
        "back end",      # пробел
        "back_end",      # подчёркивание не разрешено по ADR-002 §2.2
        "1backend",      # начинается с цифры
        "x",             # короче 2 символов
        "-backend",      # начинается с дефиса
    ],
)
def test_invalid_slug(tmp_path: Path, bad_name: str) -> None:
    content = f"""---
schema_version: 1
name: {bad_name}
description: bad slug test
llm: claude
model: claude-sonnet-4-5
---
body here is long enough
"""
    p = _write(tmp_path / "bad-slug.md", content)
    result = validate_role_file(p)

    assert result.ok is False, f"slug {bad_name!r} unexpectedly passed"
    assert any("name" in e.lower() and "slug" in e.lower() for e in result.errors), \
        f"expected slug error for {bad_name!r}, got {result.errors}"


def test_empty_body(tmp_path: Path) -> None:
    content = """---
schema_version: 1
name: empty
description: role with empty body
llm: claude
model: claude-sonnet-4-5
---
"""
    p = _write(tmp_path / "empty-body.md", content)
    result = validate_role_file(p)

    assert result.ok is False
    assert any("body" in e.lower() and ("empty" in e.lower() or "short" in e.lower())
               for e in result.errors), \
        f"expected empty-body error, got {result.errors}"


def test_body_too_short(tmp_path: Path) -> None:
    content = """---
schema_version: 1
name: short
description: role with too-short body
llm: claude
model: claude-sonnet-4-5
---
hi
"""
    p = _write(tmp_path / "short-body.md", content)
    result = validate_role_file(p)
    assert result.ok is False
    assert any("body" in e.lower() for e in result.errors)


def test_missing_frontmatter(tmp_path: Path) -> None:
    p = _write(tmp_path / "plain.md", "Just a markdown file. No frontmatter.")
    result = validate_role_file(p)

    assert result.ok is False
    assert any("frontmatter" in e.lower() for e in result.errors)


def test_invalid_yaml(tmp_path: Path) -> None:
    content = """---
schema_version: 1
name: foo
description: [unclosed
llm: claude
model: x
---
body
"""
    p = _write(tmp_path / "bad-yaml.md", content)
    result = validate_role_file(p)
    assert result.ok is False
    assert any("yaml" in e.lower() for e in result.errors)


def test_file_not_found(tmp_path: Path) -> None:
    result = validate_role_file(tmp_path / "does-not-exist.md")
    assert result.ok is False
    assert any("not found" in e.lower() for e in result.errors)


def test_wrong_schema_version(tmp_path: Path) -> None:
    content = """---
schema_version: 2
name: foo
description: future schema
llm: claude
model: claude-sonnet-4-5
---
body here is long enough
"""
    p = _write(tmp_path / "future.md", content)
    result = validate_role_file(p)
    assert result.ok is False
    assert any("schema_version" in e for e in result.errors)


def test_temperature_out_of_range(tmp_path: Path) -> None:
    content = """---
schema_version: 1
name: foo
description: bad temp
llm: claude
model: claude-sonnet-4-5
temperature: 5.0
---
body here is long enough
"""
    p = _write(tmp_path / "hot.md", content)
    result = validate_role_file(p)
    assert result.ok is False
    assert any("temperature" in e for e in result.errors)


def test_description_too_long(tmp_path: Path) -> None:
    content = """---
schema_version: 1
name: foo
description: """ + ("x" * 200) + """
llm: claude
model: claude-sonnet-4-5
---
body here is long enough
"""
    p = _write(tmp_path / "long-desc.md", content)
    result = validate_role_file(p)
    assert result.ok is False
    assert any("description" in e for e in result.errors)


# ---------------------------------------------------------------------------
# validate_all + CLI
# ---------------------------------------------------------------------------


def test_validate_all_directory(tmp_path: Path) -> None:
    _write(tmp_path / "good.md", VALID_FRONTMATTER)
    _write(
        tmp_path / "bad.md",
        VALID_FRONTMATTER.replace("name: backend", "name: BadSlug"),
    )
    # Файл без расширения .md — игнорируется validate_all.
    _write(tmp_path / "notrole.txt", "irrelevant")

    results = validate_all(tmp_path)

    assert set(results.keys()) == {"good.md", "bad.md"}
    assert results["good.md"].ok is True
    assert results["bad.md"].ok is False


def test_validate_all_missing_dir(tmp_path: Path) -> None:
    with pytest.raises(RoleConfigError):
        validate_all(tmp_path / "nonexistent")


def test_cli_all_ok(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = _write(tmp_path / "ok.md", VALID_FRONTMATTER)
    rc = validator_main([str(p)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "OK" in captured.out
    assert "body=" in captured.out


def test_cli_one_fail_exit_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ok = _write(tmp_path / "ok.md", VALID_FRONTMATTER)
    bad = _write(
        tmp_path / "bad.md",
        VALID_FRONTMATTER.replace("llm: claude", "llm: nope"),
    )
    rc = validator_main([str(ok), str(bad)])
    captured = capsys.readouterr()
    assert rc == 1
    assert "OK" in captured.out
    assert "FAIL" in captured.out


def test_cli_glob_pattern(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(tmp_path / "a.md", VALID_FRONTMATTER)
    _write(tmp_path / "b.md", VALID_FRONTMATTER.replace("name: backend", "name: other"))
    rc = validator_main([str(tmp_path / "*.md")])
    captured = capsys.readouterr()
    assert rc == 0
    # Оба файла должны фигурировать.
    assert "a.md" in captured.out and "b.md" in captured.out


def test_cli_subprocess_executable() -> None:
    """`python -m roles.validator <bad-path>` отрабатывает с exit-code 1.

    Smoke-проверка что точка входа `__main__` корректно подключена.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "roles.validator", "/no/such/path.md"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "FAIL" in proc.stdout or "no files matched" in proc.stderr


# ---------------------------------------------------------------------------
# Existing 7 role files — known-limitation smoke test
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not EXISTING_ROLES_DIR.exists(),
    reason="каталог roles/ отсутствует (репо не в исходной структуре)",
)
def test_existing_roles_validator_does_not_crash() -> None:
    """Существующие 7 файлов используют legacy-формат (ADR-002 §2.6).

    Они НЕ должны пройти strict-валидацию (нет `schema_version`, `name`,
    `llm`, `model`). Проверяем что validate_all:
        1) не падает с исключением,
        2) возвращает структурированные ошибки для каждого файла,
        3) фиксирует факт что миграция (E7.2) ещё не сделана.

    Если этот тест когда-то начнёт падать с ok=True для legacy-файлов
    — это значит, что миграция выполнена; тест нужно будет переписать.
    """
    results = validate_all(EXISTING_ROLES_DIR)

    # Должны быть найдены файлы (хотя бы 1).
    assert len(results) >= 1, "ожидаются файлы в roles/"

    # Все legacy-файлы должны падать с понятными ошибками про
    # missing required fields (schema_version / name / llm / model).
    for filename, result in results.items():
        assert isinstance(result, ValidationResult)
        if result.ok:
            # Если файл уже мигрирован — отлично, пропускаем.
            continue
        joined = " | ".join(result.errors)
        # Хотя бы одна из ожидаемых проблем legacy-формата.
        legacy_markers = ["schema_version", "name", "llm", "model"]
        assert any(m in joined for m in legacy_markers), (
            f"{filename}: ошибки не содержат ожидаемых legacy-маркеров: "
            f"{result.errors}"
        )

"""Валидатор формата файлов ролей `roles/*.md` (ADR-002).

Парсит YAML-frontmatter + markdown-тело, валидирует frontmatter по
pydantic-схеме `RoleConfig` (ADR-002 §2.5) и проверяет ограничения по
размеру файла (50 KB hard-limit, §2.4) и непустому телу промта.

Использование как модуль:

    from roles.validator import validate_role_file
    result = validate_role_file("roles/тимлид.md")
    if not result.ok:
        for err in result.errors:
            print(err)

CLI-режим:

    python -m roles.validator roles/*.md

Возвращает exit-code 1 если хоть один файл не прошёл валидацию.

Known limitation
----------------
Существующие 7 файлов в `roles/*.md` используют legacy-формат
(кириллические ключи, отсутствуют обязательные `schema_version`,
`name`, `llm`, `model`). Они не пройдут strict-валидацию по ADR-002 —
это ожидаемо. Миграция файлов — отдельная задача E7.2 (см. §2.6 ADR).
Кириллические значения в `name:` (`name: тимлид`) тоже не пройдут
slug-regex (`^[a-z][a-z0-9-]{1,31}$`) — это сознательное решение
ADR-002 §2.2 (machine identifiers — latin only).
"""

from __future__ import annotations

import argparse
import glob as _glob
import re
import sys
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator


# 50 KB hard-limit (ADR-002 §2.4). Точная единица — 50 * 1024 байт.
MAX_ROLE_FILE_SIZE = 50 * 1024

# Минимальная длина непустого тела системного промта (после frontmatter).
# 10 символов — sanity-check, защищает от пустого файла с только frontmatter.
MIN_BODY_LENGTH = 10

# Регексы разделителей frontmatter. Допускаем CRLF/LF/whitespace по краям.
_FRONTMATTER_RE = re.compile(
    r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n(.*)$",
    re.DOTALL,
)

# Slug-regex для CLI-вывода (ADR-002 §2.2). Дублируется в pydantic-схеме.
_SLUG_PATTERN = r"^[a-z][a-z0-9-]{1,31}$"


class RoleConfigError(Exception):
    """Ошибка формата файла роли (ADR-002 §2.5).

    Бросается из публичных функций загрузчика. Валидатор сам по себе
    `RoleConfigError` не бросает — собирает все ошибки в
    `ValidationResult.errors`. Класс экспортируется как часть публичного
    API, чтобы будущий `load_role()` (E7.2) мог его использовать.
    """


class RoleConfig(BaseModel):
    """Конфигурация роли из frontmatter файла `roles/<name>.md`.

    Соответствует ADR-002 §2.5. Обязательные поля (§2.2):
    `schema_version`, `name`, `description`, `llm`, `model`.
    Опциональные (§2.3): `tools`, `temperature`, `max_tokens`, `extras`.

    `model_config = {"extra": "allow"}` — legacy-поля из существующих
    файлов (`тип`, `роль`, `проект`, ...) сохраняются в `model_extra` и
    не валидируются, см. §2.6.
    """

    schema_version: Literal[1]
    name: str = Field(pattern=_SLUG_PATTERN)
    description: str = Field(min_length=1, max_length=100)
    llm: Literal["claude", "openai", "ollama"]
    model: str = Field(min_length=1)

    tools: list[str] | Literal["*"] = "*"
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    max_tokens: int = Field(default=8192, ge=1, le=200_000)
    extras: dict[str, Any] = Field(default_factory=dict)

    # Legacy + неизвестные поля разрешены (ADR-002 §2.6).
    model_config = {"extra": "allow"}

    @field_validator("tools")
    @classmethod
    def _validate_tools(cls, v: Any) -> Any:
        if v == "*":
            return v
        if not isinstance(v, list) or not all(isinstance(t, str) for t in v):
            raise ValueError("tools must be '*' or list[str]")
        return v

    @field_validator("description")
    @classmethod
    def _description_single_line(cls, v: str) -> str:
        if "\n" in v.strip():
            raise ValueError("description must be single-line")
        return v


class ValidationResult(BaseModel):
    """Результат валидации одного файла роли.

    Поля:
        ok           — True если файл прошёл все проверки.
        errors       — список человеко-читаемых ошибок (пустой если ok=True).
        config       — распарсенный `RoleConfig` если frontmatter валиден,
                       иначе None.
        body_length  — длина тела (символы) после frontmatter. 0 если
                       frontmatter не распарсился.
    """

    ok: bool
    errors: list[str] = Field(default_factory=list)
    config: RoleConfig | None = None
    body_length: int = 0


# ---------------------------------------------------------------------------
# Внутренние helpers
# ---------------------------------------------------------------------------


def _split_frontmatter(text: str) -> tuple[str, str] | None:
    """Разделить текст на (frontmatter, body). Возвращает None если
    разделители `---` не найдены или формат сломан."""
    if not text.lstrip().startswith("---"):
        return None
    # Уберём BOM/начальные пробелы перед первой `---`, чтобы regex сработал.
    stripped = text.lstrip("﻿").lstrip()
    m = _FRONTMATTER_RE.match(stripped)
    if not m:
        return None
    return m.group(1), m.group(2)


def _format_pydantic_errors(exc: ValidationError) -> list[str]:
    """Превратить pydantic ValidationError в список человекочитаемых строк.

    Спецобработка для `llm` (Literal) — выводим допустимые значения явно,
    как требует acceptance задачи.
    """
    out: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ())) or "<root>"
        msg = err.get("msg", "invalid")
        err_type = err.get("type", "")

        # Спецсообщение для llm-enum (ADR-002 §2.2).
        if loc == "llm" and "literal_error" in err_type:
            out.append("field 'llm' must be one of: claude, openai, ollama")
            continue

        # Спецсообщение для невалидного slug в name.
        if loc == "name" and "string_pattern_mismatch" in err_type:
            out.append(
                f"field 'name' must be lowercase slug matching "
                f"{_SLUG_PATTERN} (e.g. 'backend', 'qa-lead')"
            )
            continue

        # Missing required.
        if err_type == "missing":
            out.append(f"field '{loc}' is required")
            continue

        out.append(f"field '{loc}': {msg}")
    return out


# ---------------------------------------------------------------------------
# Публичный API
# ---------------------------------------------------------------------------


def validate_role_file(path: Path | str) -> ValidationResult:
    """Провалидировать один файл роли.

    Не бросает исключений — все ошибки собираются в `ValidationResult.errors`.
    Если файл не существует / не читается — это тоже фиксируется как
    ошибка валидации (ok=False), а не raise.
    """
    p = Path(path)
    errors: list[str] = []

    # 1. Существование и чтение.
    if not p.exists():
        return ValidationResult(ok=False, errors=[f"file not found: {p}"])
    if not p.is_file():
        return ValidationResult(ok=False, errors=[f"not a regular file: {p}"])

    # 2. Размер файла (ADR-002 §2.4).
    try:
        size = p.stat().st_size
    except OSError as e:
        return ValidationResult(ok=False, errors=[f"cannot stat {p}: {e}"])

    if size > MAX_ROLE_FILE_SIZE:
        return ValidationResult(
            ok=False,
            errors=[
                f"file exceeds 50KB limit "
                f"({size} bytes > {MAX_ROLE_FILE_SIZE} bytes)"
            ],
        )

    # 3. Чтение содержимого (UTF-8).
    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        return ValidationResult(
            ok=False,
            errors=[f"file is not valid UTF-8: {e}"],
        )
    except OSError as e:
        return ValidationResult(ok=False, errors=[f"cannot read {p}: {e}"])

    # 4. Разделение frontmatter / body.
    split = _split_frontmatter(text)
    if split is None:
        return ValidationResult(
            ok=False,
            errors=[
                "missing YAML frontmatter (expected '---' on first line, "
                "another '---' below, then markdown body)"
            ],
        )
    frontmatter_text, body = split
    body_length = len(body)

    # 5. Парсинг YAML.
    try:
        fm_dict = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError as e:
        return ValidationResult(
            ok=False,
            errors=[f"invalid YAML in frontmatter: {e}"],
            body_length=body_length,
        )

    if fm_dict is None:
        return ValidationResult(
            ok=False,
            errors=["frontmatter is empty"],
            body_length=body_length,
        )
    if not isinstance(fm_dict, dict):
        return ValidationResult(
            ok=False,
            errors=[
                f"frontmatter must be a YAML mapping, "
                f"got {type(fm_dict).__name__}"
            ],
            body_length=body_length,
        )

    # 6. Валидация через pydantic.
    config: RoleConfig | None = None
    try:
        config = RoleConfig.model_validate(fm_dict)
    except ValidationError as exc:
        errors.extend(_format_pydantic_errors(exc))

    # 7. Проверка тела (минимум MIN_BODY_LENGTH символов после strip).
    if len(body.strip()) < MIN_BODY_LENGTH:
        errors.append(
            f"body is empty or too short "
            f"(need at least {MIN_BODY_LENGTH} non-whitespace chars)"
        )

    ok = not errors
    return ValidationResult(
        ok=ok,
        errors=errors,
        config=config if ok else config,  # config может быть полезен и при FAIL для дебага
        body_length=body_length,
    )


def validate_all(directory: Path | str) -> dict[str, ValidationResult]:
    """Батч-валидация всех `*.md` в директории.

    Возвращает словарь {имя_файла: ValidationResult}. Не рекурсивно —
    смотрит только верхний уровень. Сортировка ключей — алфавитная.
    """
    d = Path(directory)
    if not d.exists():
        raise RoleConfigError(f"directory not found: {d}")
    if not d.is_dir():
        raise RoleConfigError(f"not a directory: {d}")

    results: dict[str, ValidationResult] = {}
    for md_file in sorted(d.glob("*.md")):
        results[md_file.name] = validate_role_file(md_file)
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _expand_paths(patterns: list[str]) -> list[Path]:
    """Развернуть glob-паттерны в конкретные пути.

    Дубликаты убираем (сохраняя порядок первого вхождения). Если паттерн
    не матчит ничего — оставляем как есть, чтобы validate_role_file
    выдал понятный "file not found".
    """
    seen: set[str] = set()
    out: list[Path] = []
    for pat in patterns:
        matches = _glob.glob(pat)
        if not matches:
            # Не матчится — передаём как есть, валидатор скажет "file not found".
            if pat not in seen:
                seen.add(pat)
                out.append(Path(pat))
            continue
        for m in matches:
            if m not in seen:
                seen.add(m)
                out.append(Path(m))
    return out


def _format_size(n_bytes: int) -> str:
    """Человеко-читаемый размер: '5.2KB' / '923B'."""
    if n_bytes < 1024:
        return f"{n_bytes}B"
    return f"{n_bytes / 1024:.1f}KB"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m roles.validator",
        description="Validate role files (ADR-002 format).",
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help="One or more file paths or glob patterns (e.g. roles/*.md).",
    )
    args = parser.parse_args(argv)

    files = _expand_paths(args.paths)
    if not files:
        print("no files matched", file=sys.stderr)
        return 1

    any_fail = False
    for f in files:
        result = validate_role_file(f)
        if result.ok:
            print(f"{f}: OK (body={_format_size(result.body_length)})")
        else:
            any_fail = True
            # Первая ошибка — в основной строке для компактности.
            first = result.errors[0] if result.errors else "unknown error"
            print(f"{f}: FAIL — {first}")
            # Остальные — с отступом.
            for extra in result.errors[1:]:
                print(f"    {extra}")

    return 1 if any_fail else 0


if __name__ == "__main__":
    sys.exit(main())

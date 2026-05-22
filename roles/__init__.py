"""Пакет `roles` — формат и загрузка ролей pride-team.

Сейчас содержит только валидатор формата (`roles.validator`). Полноценный
загрузчик `load_role()` — задача E7.2 (см. `docs/adr/0002-role-format.md`).

Публичный API:
    RoleConfig           — pydantic-схема frontmatter роли (ADR-002 §2.5).
    RoleConfigError      — единый exception для ошибок формата роли.
    ValidationResult     — структурированный результат валидации файла.
    validate_role_file() — валидация одного файла роли.
    validate_all()       — батч-валидация директории.

Импорты ленивые (через `__getattr__`), чтобы `python -m roles.validator`
не выдавал runpy-warning о двойном импорте модуля.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = [
    "RoleConfig",
    "RoleConfigError",
    "ValidationResult",
    "validate_all",
    "validate_role_file",
]


if TYPE_CHECKING:  # pragma: no cover - только для type-checker'ов
    from .validator import (
        RoleConfig,
        RoleConfigError,
        ValidationResult,
        validate_all,
        validate_role_file,
    )


def __getattr__(name: str) -> Any:
    if name in __all__:
        from . import validator

        return getattr(validator, name)
    raise AttributeError(f"module 'roles' has no attribute {name!r}")

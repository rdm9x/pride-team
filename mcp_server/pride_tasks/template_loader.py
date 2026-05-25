"""Template loader: HR-bypass fast-path для v2-шаблонов отделов (ADR-009 §2.5, §2.7.1).

Содержит helper `load_role_with_inherits` который собирает финальный system_prompt
для роли v2-шаблона: base body из roles/<dept>/<slug>.md + содержимое всех
SKILL.md из inherits_skills (из vendored/knowledge-work-plugins/<dept>/skills/<skill>/SKILL.md).

Используется dashboard endpoint POST /api/departments (см. app.py) когда
template_id оканчивается на '-v2' — это fast-path, минуя HR-pipeline (ADR-004).

См. также ADR-009 §8 task B5 (inherits_skills mechanism).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _read_skill_md(vendored_root: Path, dept_slug: str, skill_slug: str) -> str | None:
    """Прочитать SKILL.md одного скилла. None если файла нет."""
    path = vendored_root / dept_slug / "skills" / skill_slug / "SKILL.md"
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def _read_role_base(roles_root: Path, dept_slug: str, role_slug: str) -> str:
    """Прочитать roles/<dept>/<slug>.md (markdown без frontmatter обработки).

    Возвращает пустую строку если файла нет — это валидный случай для v2
    шаблонов когда base-роли ещё не материализованы на диск.
    """
    path = roles_root / dept_slug / f"{role_slug}.md"
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def load_role_with_inherits(
    role_yaml: dict[str, Any],
    dept_slug: str,
    vendored_root: Path,
    *,
    roles_root: Path,
) -> str:
    """Собрать финальный system_prompt для роли из v2-шаблона.

    Args:
        role_yaml: dict одной роли из YAML-шаблона (поля: slug, inherits_skills, ...).
        dept_slug: slug отдела (e.g. 'marketing').
        vendored_root: путь к vendored/knowledge-work-plugins/.
        roles_root: путь к roles/ (репо-уровень).

    Returns:
        Строка: base content из roles/<dept>/<slug>.md (если есть) +
        '\\n\\n## Inherited skills\\n\\n' + конкатенация всех SKILL.md
        (каждая под '### Skill: <slug>'). Если inherits_skills пустой —
        возвращается только base без секции Inherited skills.

    Raises:
        ValueError: если хотя бы один из inherits_skills не найден в
            vendored_root/<dept>/skills/<skill>/SKILL.md. Сообщение содержит
            список отсутствующих скиллов.
    """
    role_slug = role_yaml.get("slug")
    if not role_slug:
        raise ValueError("role_yaml без поля 'slug'")

    inherits = role_yaml.get("inherits_skills") or []
    if not isinstance(inherits, list):
        raise ValueError(
            f"role {role_slug}: inherits_skills должен быть list, получен "
            f"{type(inherits).__name__}"
        )

    base = _read_role_base(roles_root, dept_slug, role_slug)

    # Если нет наследуемых скиллов — возвращаем только base (или пустую строку).
    if not inherits:
        return base

    # Загружаем скиллы, собираем missing.
    skill_chunks: list[str] = []
    missing: list[str] = []
    for skill in inherits:
        content = _read_skill_md(vendored_root, dept_slug, skill)
        if content is None:
            missing.append(skill)
            continue
        skill_chunks.append(f"### Skill: {skill}\n\n{content.strip()}\n")

    if missing:
        raise ValueError(
            f"role {role_slug}: missing SKILL.md files in "
            f"{vendored_root}/{dept_slug}/skills/: {missing}"
        )

    parts: list[str] = []
    if base.strip():
        parts.append(base.rstrip())
    parts.append("## Inherited skills")
    parts.extend(skill_chunks)
    return "\n\n".join(parts).rstrip() + "\n"


__all__ = ["load_role_with_inherits"]

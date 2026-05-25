#!/usr/bin/env python3
"""Audit для проверки что не осталось старых ссылок на pride."""

import os
import re
from pathlib import Path

PATTERNS = [
    r'pride_tasks',
    r'pride-tasks',
    r'PRIDE_[A-Z_]+',
    r'pride-team',
    r'pride_team',
]

EXCLUDE_DIRS = {'.git', '.venv', '__pycache__', 'node_modules', '.pytest_cache', 'htmlcov'}
EXCLUDE_FILES = {'.pyc', '.pyo', '.db', '.db-shm', '.db-wal', '.db.lock', '.log'}

# Исторические исключения (допустимо в истории)
ALLOW_PATHS = {
    'docs/adr',       # Исторические ADR
    'CHANGELOG',      # История изменений
    '.git',           # Git история
    '.venv',          # Виртуальное окружение
}

def should_skip_file(path: Path) -> bool:
    """Проверить должен ли быть пропущен файл."""
    if any(part in EXCLUDE_DIRS for part in path.parts):
        return True
    if any(path.suffix == ext for ext in EXCLUDE_FILES):
        return True
    return False

def check_file(path: Path) -> list[tuple[int, str]]:
    """Проверить файл на старые ссылки. Возвращает список (линия, совпадение)."""
    if should_skip_file(path):
        return []

    if not path.is_file():
        return []

    # Пропускаем бинарные файлы
    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except (UnicodeDecodeError, IOError):
        return []

    issues = []
    for line_no, line in enumerate(lines, 1):
        for pattern in PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                # Проверить что не в разрешённом месте
                if not any(allow in str(path) for allow in ALLOW_PATHS):
                    issues.append((line_no, line.strip()))

    return issues

def main():
    root = Path(__file__).resolve().parent
    violations = {}

    for path in root.rglob('*'):
        if path.is_file():
            issues = check_file(path)
            if issues:
                rel_path = str(path.relative_to(root))
                violations[rel_path] = issues

    if violations:
        print("❌ Найдены старые ссылки на pride:")
        for file_path, issues in sorted(violations.items()):
            print(f"\n  {file_path}:")
            for line_no, line in issues:
                print(f"    строка {line_no}: {line[:100]}")
        return 1
    else:
        print("✓ Старых ссылок на pride не найдено")
        return 0

if __name__ == '__main__':
    exit(main())

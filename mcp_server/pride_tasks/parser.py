"""Парсер description на структурированные секции.

Поддерживает:
- **TL;DR**: короткое резюме в одну строку (24px, accent)
- ## Что делать / ## Steps: список шагов с галочками
- ## Acceptance / ## Acceptance Criteria: чек-лист
- Варианты вопросов (### Вариант X, - Опция 1, etc.): кнопки для быстрого ответа

Результат — структурированный JSON для frontend.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any, Optional


@dataclass
class ParsedTask:
    """Результат парсинга description."""

    # TL;DR — одна строка
    tldr: Optional[str] = None

    # Шаги/What to do: список строк
    steps: list[str] | None = None

    # Acceptance criteria: список чек-листов (название + варианты)
    acceptance: list[dict[str, Any]] | None = None

    # Варианты ответов для кнопок: [{"label": "...", "value": "..."}]
    options: list[dict[str, str]] | None = None

    # Исходный markdown (для agent-mode)
    raw_markdown: str = ""

    # Есть ли структура (для fallback к raw если пусто)
    has_structure: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Преобразовать в dict для JSON."""
        return asdict(self)


def parse_task_description(description: str) -> ParsedTask:
    """Распарсить description на структурированные части.

    Args:
        description: исходный markdown-текст

    Returns:
        ParsedTask с выделенными секциями
    """
    if not description or not description.strip():
        return ParsedTask(raw_markdown=description, has_structure=False)

    result = ParsedTask(raw_markdown=description)
    lines = description.split('\n')

    # 1. Ищем TL;DR
    result.tldr = _extract_tldr(description)

    # 2. Ищем шаги (## Что делать, ## Steps, ## Задачи и т.д.)
    result.steps = _extract_steps(description)

    # 3. Ищем acceptance criteria / чек-лист
    result.acceptance = _extract_acceptance(description)

    # 4. Ищем варианты ответов (вопросы с опциями)
    result.options = _extract_options(description)

    # Отмечаем наличие структуры
    result.has_structure = bool(result.tldr or result.steps or result.acceptance or result.options)

    return result


def _extract_tldr(text: str) -> Optional[str]:
    """Извлечь TL;DR из начала текста.

    Ищет:
    - **TL;DR**: ...
    - **TL;DR**:...
    - **TL;DR** ...
    - TLDR: ... (любой вариант с разными пунктуацией)
    """
    # Несколько вариантов регекса для гибкости
    patterns = [
        r'^\s*\*\*TL;?DR\*\*\s*:?\s*([^\n]+)',
        r'^\s*TL;?DR\s*:?\s*([^\n]+)',
        r'^\*+TL;?DR\*+\s*:?\s*([^\n]+)',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(1).strip()

    return None


def _extract_steps(text: str) -> Optional[list[str]]:
    """Извлечь шаги из секции типа '## Что делать' или '## Steps'."""
    # Ищем header типа "## Что делать", "## Steps", "## Задачи", "## Шаги"
    step_headers = [
        r'##\s+(Что\s+делать|Steps|Задачи|Шаги|Действия)',
    ]

    steps = []
    for header_pattern in step_headers:
        match = re.search(header_pattern, text, re.IGNORECASE)
        if match:
            # Берём всё после header'а до следующего header'а или конца
            start_pos = match.end()
            next_header = re.search(r'\n##', text[start_pos:])
            end_pos = start_pos + next_header.start() if next_header else len(text)

            section = text[start_pos:end_pos]

            # Ищем пункты списка (-, *, 1. и т.д.)
            list_patterns = [
                r'^\s*[-*+]\s+(.+)$',      # bullet list
                r'^\s*\d+\.\s+(.+)$',      # numbered list
            ]

            for line in section.split('\n'):
                line = line.strip()
                if not line:
                    continue
                for list_pattern in list_patterns:
                    m = re.match(list_pattern, line)
                    if m:
                        steps.append(m.group(1).strip())
                        break

            if steps:
                return steps

    return None if not steps else steps


def _extract_acceptance(text: str) -> Optional[list[dict[str, Any]]]:
    """Извлечь acceptance criteria / чек-лист.

    Ищет:
    - ## Acceptance / ## Acceptance Criteria
    - [ ] checkbox-list
    """
    # Ищем header
    acceptance_patterns = [
        r'##\s+(Acceptance|Acceptance\s+Criteria|Критерии|Чек-лист)',
    ]

    criteria = []
    for pattern in acceptance_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            start_pos = match.end()
            next_header = re.search(r'\n##', text[start_pos:])
            end_pos = start_pos + next_header.start() if next_header else len(text)

            section = text[start_pos:end_pos]

            # Ищем [ ] checkbox-list
            checkbox_pattern = r'^\s*\[\s*([xX ]?)\s*\]\s*(.+)$'

            for line in section.split('\n'):
                m = re.match(checkbox_pattern, line)
                if m:
                    checked = m.group(1).lower() in ('x', 'X')
                    label = m.group(2).strip()
                    criteria.append({
                        'checked': checked,
                        'label': label
                    })

            if criteria:
                return criteria

    return None if not criteria else criteria


def _extract_options(text: str) -> Optional[list[dict[str, str]]]:
    """Извлечь варианты ответов (вопросы с опциями для кнопок).

    Ищет паттерны типа:
    ### Вариант 1
    - Опция A
    - Опция B

    Или просто список опций без явного header'а.
    """
    options = []

    # Паттерн: строка с "Вариант"/"Option"/"Выбери"/"Choose"/"Как" и список после
    # Может быть 2 или 3 уровня header'а
    option_patterns = [
        r'#{2,3}\s+(Вариант|Option|Выбери|Choose|Какой|Which|Как)[^\n]*',
    ]

    for pattern in option_patterns:
        matches = re.finditer(pattern, text, re.IGNORECASE)
        for match in matches:
            start_pos = match.end()
            # Берём строки до следующего ### или ##
            next_marker = re.search(r'\n[#]{2,3}', text[start_pos:])
            end_pos = start_pos + next_marker.start() if next_marker else len(text)

            section = text[start_pos:end_pos]

            # Ищем bullet list
            for line in section.split('\n'):
                m = re.match(r'^\s*[-*+]\s+(.+)$', line)
                if m:
                    option_text = m.group(1).strip()
                    # Value — нормализованный вариант label
                    value = option_text.lower().replace(' ', '_')
                    options.append({
                        'label': option_text,
                        'value': value
                    })

    return options if options else None

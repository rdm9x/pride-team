"""Тесты для парсера description задач.

Проверяет извлечение:
- TL;DR
- Шаги (## Что делать, ## Steps, и т.д.)
- Acceptance criteria (## Acceptance, checkbox-list)
- Варианты ответов (для кнопок)
"""

import pytest
import sys
from pathlib import Path

# Импортируем парсер из mcp_server
_MCP_DIR = Path(__file__).resolve().parent.parent / "mcp_server"
if str(_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_MCP_DIR))

from pride_tasks.parser import parse_task_description, ParsedTask


class TestExtractTldr:
    """Тесты извлечения TL;DR."""

    def test_tldr_with_bold_and_colon(self):
        text = "**TL;DR**: сделать фичу быстро и хорошо"
        parsed = parse_task_description(text)
        assert parsed.tldr == "сделать фичу быстро и хорошо"

    def test_tldr_with_bold_no_colon(self):
        text = "**TL;DR** добавить новый API endpoint"
        parsed = parse_task_description(text)
        assert parsed.tldr == "добавить новый API endpoint"

    def test_tldr_without_semicolon(self):
        text = "**TLDR**: Исправить баг в авторизации"
        parsed = parse_task_description(text)
        assert parsed.tldr == "Исправить баг в авторизации"

    def test_tldr_case_insensitive(self):
        text = "**tldr**: small fix in parser"
        parsed = parse_task_description(text)
        assert parsed.tldr == "small fix in parser"

    def test_tldr_multiline_takes_first_line(self):
        text = """**TL;DR**: сделать это
        и это
        и это"""
        parsed = parse_task_description(text)
        assert parsed.tldr == "сделать это"

    def test_no_tldr(self):
        text = "Вот текст без TL;DR"
        parsed = parse_task_description(text)
        assert parsed.tldr is None


class TestExtractSteps:
    """Тесты извлечения шагов."""

    def test_steps_with_bullet_list(self):
        text = """## Что делать

- Создать новый файл
- Добавить функцию
- Запустить тесты"""
        parsed = parse_task_description(text)
        assert parsed.steps == ["Создать новый файл", "Добавить функцию", "Запустить тесты"]

    def test_steps_with_numbered_list(self):
        text = """## Steps

1. Create component
2. Add tests
3. Update docs"""
        parsed = parse_task_description(text)
        assert parsed.steps == ["Create component", "Add tests", "Update docs"]

    def test_steps_with_mixed_bullet(self):
        text = """## Задачи

* Шаг первый
+ Шаг второй
- Шаг третий"""
        parsed = parse_task_description(text)
        assert len(parsed.steps) == 3
        assert "Шаг первый" in parsed.steps
        assert "Шаг второй" in parsed.steps
        assert "Шаг третий" in parsed.steps

    def test_steps_stops_at_next_header(self):
        text = """## Что делать

- Шаг 1
- Шаг 2

## Acceptance

[ ] критерий"""
        parsed = parse_task_description(text)
        assert parsed.steps == ["Шаг 1", "Шаг 2"]

    def test_no_steps(self):
        text = "Просто какой-то текст без шагов"
        parsed = parse_task_description(text)
        assert parsed.steps is None


class TestExtractAcceptance:
    """Тесты извлечения acceptance criteria."""

    def test_acceptance_checkbox_list(self):
        text = """## Acceptance

[ ] Функция работает
[x] Тесты пройдены
[ ] Документация обновлена"""
        parsed = parse_task_description(text)
        assert parsed.acceptance is not None
        assert len(parsed.acceptance) == 3
        assert parsed.acceptance[0] == {"checked": False, "label": "Функция работает"}
        assert parsed.acceptance[1] == {"checked": True, "label": "Тесты пройдены"}
        assert parsed.acceptance[2] == {"checked": False, "label": "Документация обновлена"}

    def test_acceptance_checked_uppercase(self):
        text = """## Acceptance Criteria

[X] API возвращает 200
[ ] Кеш работает"""
        parsed = parse_task_description(text)
        assert parsed.acceptance is not None
        assert parsed.acceptance[0]["checked"] is True
        assert parsed.acceptance[1]["checked"] is False

    def test_acceptance_with_spaces_in_checkbox(self):
        text = """## Acceptance

[ ] Критерий 1
[  X  ] Критерий 2"""
        parsed = parse_task_description(text)
        assert parsed.acceptance is not None
        assert len(parsed.acceptance) == 2
        assert parsed.acceptance[0]["checked"] is False
        assert parsed.acceptance[1]["checked"] is True

    def test_no_acceptance(self):
        text = "Текст без acceptance критериев"
        parsed = parse_task_description(text)
        assert parsed.acceptance is None


class TestExtractOptions:
    """Тесты извлечения вариантов ответов."""

    def test_options_with_variant_header(self):
        text = """### Вариант реализации

- Использовать REST API
- Использовать GraphQL
- Использовать WebSocket"""
        parsed = parse_task_description(text)
        assert parsed.options is not None
        assert len(parsed.options) == 3
        assert parsed.options[0]["label"] == "Использовать REST API"
        assert parsed.options[0]["value"] == "использовать_rest_api"

    def test_options_with_choose_header(self):
        text = """### Какой тип авторизации?

- OAuth 2.0
- JWT
- Basic Auth"""
        parsed = parse_task_description(text)
        assert parsed.options is not None
        assert len(parsed.options) == 3

    def test_options_normalized_value(self):
        text = """### Вариант

- Очень длинный текст опции
- Another Option"""
        parsed = parse_task_description(text)
        assert parsed.options[0]["value"] == "очень_длинный_текст_опции"
        assert parsed.options[1]["value"] == "another_option"

    def test_no_options(self):
        text = "Текст без вариантов"
        parsed = parse_task_description(text)
        assert parsed.options is None


class TestHasStructure:
    """Тесты флага has_structure."""

    def test_has_structure_with_tldr(self):
        text = "**TL;DR**: быстрая фича"
        parsed = parse_task_description(text)
        assert parsed.has_structure is True

    def test_has_structure_with_steps(self):
        text = "## Что делать\n- Шаг 1"
        parsed = parse_task_description(text)
        assert parsed.has_structure is True

    def test_has_structure_with_acceptance(self):
        text = "## Acceptance\n[ ] Критерий"
        parsed = parse_task_description(text)
        assert parsed.has_structure is True

    def test_has_structure_with_options(self):
        text = "### Вариант\n- Опция 1"
        parsed = parse_task_description(text)
        assert parsed.has_structure is True

    def test_no_structure(self):
        text = "Просто текст без структуры"
        parsed = parse_task_description(text)
        assert parsed.has_structure is False

    def test_empty_text(self):
        text = ""
        parsed = parse_task_description(text)
        assert parsed.has_structure is False


class TestComplexDescription:
    """Тесты полноценных descriptions с несколькими секциями."""

    def test_full_structured_description(self):
        text = """**TL;DR**: Реализовать двухслойное окно задачи с user и agent режимами

## Что делать

- Создать парсер markdown на структурированные части
- Добавить endpoint /api/tasks/<id>/parsed
- Реализовать user-mode UI с TL;DR, шагами, acceptance
- Добавить agent-mode с технически деталями

## Acceptance

[ ] Парсер извлекает TL;DR
[x] Шаги отображаются со списком
[ ] Acceptance criteria как чек-лист
[ ] Agent-mode показывает raw markdown

### Как вы хотите реализовать?

- Через компонент Vue
- На чистом JavaScript
- React-компонент"""
        parsed = parse_task_description(text)

        assert parsed.tldr == "Реализовать двухслойное окно задачи с user и agent режимами"
        assert len(parsed.steps) == 4
        assert parsed.steps[0] == "Создать парсер markdown на структурированные части"
        assert parsed.acceptance is not None
        assert len(parsed.acceptance) == 4
        assert parsed.acceptance[0]["checked"] is False
        assert parsed.acceptance[1]["checked"] is True
        assert parsed.options is not None
        assert len(parsed.options) >= 3
        assert parsed.has_structure is True

    def test_raw_markdown_preserved(self):
        text = "**TL;DR**: Тест\n\n## Что делать\n- Пункт"
        parsed = parse_task_description(text)
        assert parsed.raw_markdown == text

    def test_to_dict_serializable(self):
        text = """**TL;DR**: Быстрая фича

## Что делать

- Шаг 1
- Шаг 2"""
        parsed = parse_task_description(text)
        d = parsed.to_dict()

        assert isinstance(d, dict)
        assert d["tldr"] == "Быстрая фича"
        assert d["steps"] == ["Шаг 1", "Шаг 2"]
        assert d["has_structure"] is True


class TestEdgeCases:
    """Граничные случаи и ошибки."""

    def test_empty_string(self):
        parsed = parse_task_description("")
        assert parsed.tldr is None
        assert parsed.steps is None
        assert parsed.acceptance is None
        assert parsed.options is None
        assert parsed.has_structure is False
        assert parsed.raw_markdown == ""

    def test_whitespace_only(self):
        parsed = parse_task_description("   \n\n  \t  ")
        assert parsed.has_structure is False

    def test_tldr_with_special_chars(self):
        text = "**TL;DR**: фикс #123: добавить @mention в кодексе API/REST"
        parsed = parse_task_description(text)
        assert parsed.tldr == "фикс #123: добавить @mention в кодексе API/REST"

    def test_steps_with_inline_code(self):
        text = """## Что делать

- Добавить функцию `foo()`
- Обновить `config.yaml`"""
        parsed = parse_task_description(text)
        assert len(parsed.steps) == 2
        assert "foo()" in parsed.steps[0]

    def test_acceptance_empty_checkbox(self):
        text = """## Acceptance

[ ]
[ ] Нормальный критерий"""
        parsed = parse_task_description(text)
        # Пусть парсер включает пустые критерии (или исключает — зависит от реализации)
        assert parsed.acceptance is not None
        assert any(c["label"] == "Нормальный критерий" for c in parsed.acceptance)

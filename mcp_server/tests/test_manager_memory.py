"""Тесты B2 (ADR-007 §2.2): 5 MCP-tools manager_memory_*.

Покрывает:
- happy path для каждой из 5 функций;
- role gate (managing-director vs другие роли);
- edge cases: пустой query, missing id, archive несуществующего, кириллица;
- search возвращает результаты с bm25-score;
- recent сортирует по updated_at DESC;
- интеграция с FTS5-триггерами.
"""

from __future__ import annotations

import time
from pathlib import Path

from devboard_tasks import tools


_MD = "managing-director"


# === manager_memory_add — happy path и валидация ===


def test_add_happy_path(db_path: Path) -> None:
    res = tools.manager_memory_add(
        text="Owner — owner owner, директор Acme.",
        source="note",
        tags=["owner", "company"],
        caller_role=_MD,
        db_path=db_path,
    )
    assert res["статус"] == "ok"
    assert isinstance(res["id"], int) and res["id"] > 0
    assert res["чанк"]["text"].startswith("Owner")
    assert res["чанк"]["source"] == "note"
    assert res["чанк"]["tags"] == ["owner", "company"]
    assert res["чанк"]["archived_at"] is None


def test_add_empty_text_returns_error(db_path: Path) -> None:
    res = tools.manager_memory_add(
        text="   ", source="note", caller_role=_MD, db_path=db_path
    )
    assert res["статус"] == "error"
    assert "пуст" in res["причина"]


def test_add_invalid_source_returns_error(db_path: Path) -> None:
    res = tools.manager_memory_add(
        text="hi", source="мусор", caller_role=_MD, db_path=db_path
    )
    assert res["статус"] == "error"


def test_add_path_and_lines_preserved(db_path: Path) -> None:
    res = tools.manager_memory_add(
        text="Чанк с path",
        source="recall",
        path="adr/0009#2.4",
        tags=["architecture"],
        caller_role=_MD,
        db_path=db_path,
    )
    assert res["статус"] == "ok"
    assert res["чанк"]["path"] == "adr/0009#2.4"


# === manager_memory_get — happy path и edge cases ===


def test_get_happy_path(db_path: Path) -> None:
    added = tools.manager_memory_add(
        text="hello world", source="note", caller_role=_MD, db_path=db_path
    )
    cid = added["id"]
    res = tools.manager_memory_get(chunk_id=cid, caller_role=_MD, db_path=db_path)
    assert res["статус"] == "ok"
    assert res["чанк"]["id"] == cid
    assert res["чанк"]["text"] == "hello world"


def test_get_missing_id_returns_not_found(db_path: Path) -> None:
    res = tools.manager_memory_get(chunk_id=999_999, caller_role=_MD, db_path=db_path)
    assert res["статус"] == "not_found"
    assert res["id"] == 999_999


def test_get_invalid_id_returns_error(db_path: Path) -> None:
    res = tools.manager_memory_get(chunk_id=0, caller_role=_MD, db_path=db_path)
    assert res["статус"] == "error"


# === manager_memory_search — FTS5, score, фильтрация ===


def test_search_happy_path(db_path: Path) -> None:
    tools.manager_memory_add(
        text="Owner отверг manager-of-managers, выбрал три уровня иерархия",
        source="recall",
        caller_role=_MD,
        db_path=db_path,
    )
    tools.manager_memory_add(
        text="Любимый цвет owner-а — синий",
        source="note",
        caller_role=_MD,
        db_path=db_path,
    )
    # NB: FTS5 unicode61 не делает стемминга по русскому языку — токены
    # сравниваются буквально, поэтому в тесте используем точную форму слова.
    res = tools.manager_memory_search(
        query="иерархия", caller_role=_MD, db_path=db_path
    )
    assert res["статус"] == "ok"
    assert res["всего"] >= 1
    found = res["результаты"][0]
    assert "иерархи" in found["text"].lower()
    # FTS5 bm25-score должен быть числом
    assert "score" in found
    assert isinstance(found["score"], float)


def test_search_empty_query_returns_empty(db_path: Path) -> None:
    tools.manager_memory_add(
        text="some content", source="note", caller_role=_MD, db_path=db_path
    )
    res = tools.manager_memory_search(query="", caller_role=_MD, db_path=db_path)
    assert res["статус"] == "ok"
    assert res["всего"] == 0
    assert res["результаты"] == []


def test_search_filter_by_source(db_path: Path) -> None:
    tools.manager_memory_add(
        text="планёрка про лендинг", source="planning", caller_role=_MD, db_path=db_path
    )
    tools.manager_memory_add(
        text="заметка про лендинг", source="note", caller_role=_MD, db_path=db_path
    )
    res = tools.manager_memory_search(
        query="лендинг", source="planning", caller_role=_MD, db_path=db_path
    )
    assert res["статус"] == "ok"
    assert res["всего"] == 1
    assert res["результаты"][0]["source"] == "planning"


def test_search_cyrillic_token(db_path: Path) -> None:
    """FTS5 с tokenize=unicode61 должна корректно искать по русским словам."""
    tools.manager_memory_add(
        text="Управляющий координирует руководителей отделов",
        source="note",
        caller_role=_MD,
        db_path=db_path,
    )
    tools.manager_memory_add(
        text="Совсем другой чанк про производство",
        source="note",
        caller_role=_MD,
        db_path=db_path,
    )
    res = tools.manager_memory_search(
        query="Управляющий", caller_role=_MD, db_path=db_path
    )
    assert res["статус"] == "ok"
    assert res["всего"] == 1
    assert "Управляющий" in res["результаты"][0]["text"]


def test_search_sorted_by_score(db_path: Path) -> None:
    """Несколько матчей — отсортированы по bm25 ASC (меньше = лучше)."""
    tools.manager_memory_add(
        text="кошки кошки кошки кошки",
        source="note",
        caller_role=_MD,
        db_path=db_path,
    )
    tools.manager_memory_add(
        text="кошки и собаки живут в доме где много окон стен дверей",
        source="note",
        caller_role=_MD,
        db_path=db_path,
    )
    res = tools.manager_memory_search(
        query="кошки", caller_role=_MD, db_path=db_path
    )
    assert res["статус"] == "ok"
    assert res["всего"] == 2
    scores = [r["score"] for r in res["результаты"]]
    # bm25: меньше = релевантнее. Список должен быть монотонно неубывающим.
    assert scores == sorted(scores), f"score не отсортирован ASC: {scores}"


def test_search_limit_pagination(db_path: Path) -> None:
    for i in range(5):
        tools.manager_memory_add(
            text=f"повторение слова {i}",
            source="note",
            caller_role=_MD,
            db_path=db_path,
        )
    res = tools.manager_memory_search(
        query="повторение", limit=2, caller_role=_MD, db_path=db_path
    )
    assert res["статус"] == "ok"
    assert res["всего"] == 2


def test_search_excludes_archived(db_path: Path) -> None:
    added = tools.manager_memory_add(
        text="секретный чанк", source="note", caller_role=_MD, db_path=db_path
    )
    cid = added["id"]
    tools.manager_memory_archive(chunk_id=cid, caller_role=_MD, db_path=db_path)
    res = tools.manager_memory_search(
        query="секретный", caller_role=_MD, db_path=db_path
    )
    assert res["статус"] == "ok"
    assert res["всего"] == 0


def test_search_invalid_limit_returns_error(db_path: Path) -> None:
    res = tools.manager_memory_search(
        query="x", limit=0, caller_role=_MD, db_path=db_path
    )
    assert res["статус"] == "error"


# === manager_memory_recent — happy path, sorting, filter ===


def test_recent_happy_path(db_path: Path) -> None:
    tools.manager_memory_add(
        text="A", source="note", caller_role=_MD, db_path=db_path
    )
    tools.manager_memory_add(
        text="B", source="note", caller_role=_MD, db_path=db_path
    )
    res = tools.manager_memory_recent(caller_role=_MD, db_path=db_path)
    assert res["статус"] == "ok"
    assert res["всего"] == 2


def test_recent_sorted_by_updated_at_desc(db_path: Path) -> None:
    """recent должна возвращать последние сверху."""
    a = tools.manager_memory_add(
        text="первый", source="note", caller_role=_MD, db_path=db_path
    )
    # Гарантируем разные updated_at (секундный гран в SQLite int-времени)
    time.sleep(1.05)
    b = tools.manager_memory_add(
        text="второй", source="note", caller_role=_MD, db_path=db_path
    )
    res = tools.manager_memory_recent(caller_role=_MD, db_path=db_path)
    assert res["статус"] == "ok"
    assert res["всего"] == 2
    # Последний созданный — первым
    assert res["чанки"][0]["id"] == b["id"]
    assert res["чанки"][1]["id"] == a["id"]


def test_recent_filter_by_source(db_path: Path) -> None:
    tools.manager_memory_add(
        text="N", source="note", caller_role=_MD, db_path=db_path
    )
    tools.manager_memory_add(
        text="R", source="recall", caller_role=_MD, db_path=db_path
    )
    res = tools.manager_memory_recent(
        source="recall", caller_role=_MD, db_path=db_path
    )
    assert res["статус"] == "ok"
    assert res["всего"] == 1
    assert res["чанки"][0]["source"] == "recall"


def test_recent_excludes_archived(db_path: Path) -> None:
    a = tools.manager_memory_add(
        text="живой", source="note", caller_role=_MD, db_path=db_path
    )
    b = tools.manager_memory_add(
        text="мёртвый", source="note", caller_role=_MD, db_path=db_path
    )
    tools.manager_memory_archive(
        chunk_id=b["id"], caller_role=_MD, db_path=db_path
    )
    res = tools.manager_memory_recent(caller_role=_MD, db_path=db_path)
    assert res["статус"] == "ok"
    assert res["всего"] == 1
    assert res["чанки"][0]["id"] == a["id"]


def test_recent_limit(db_path: Path) -> None:
    for i in range(5):
        tools.manager_memory_add(
            text=f"chunk{i}", source="note", caller_role=_MD, db_path=db_path
        )
    res = tools.manager_memory_recent(limit=2, caller_role=_MD, db_path=db_path)
    assert res["статус"] == "ok"
    assert res["всего"] == 2


# === manager_memory_archive — happy path и edge cases ===


def test_archive_happy_path(db_path: Path) -> None:
    added = tools.manager_memory_add(
        text="забыть это", source="note", caller_role=_MD, db_path=db_path
    )
    cid = added["id"]
    res = tools.manager_memory_archive(
        chunk_id=cid, caller_role=_MD, db_path=db_path
    )
    assert res["статус"] == "ok"
    # Чанк всё ещё доступен через get (soft-delete), но archived_at заполнен
    got = tools.manager_memory_get(chunk_id=cid, caller_role=_MD, db_path=db_path)
    assert got["статус"] == "ok"
    assert got["чанк"]["archived_at"] is not None


def test_archive_missing_id_returns_not_found(db_path: Path) -> None:
    res = tools.manager_memory_archive(
        chunk_id=12345, caller_role=_MD, db_path=db_path
    )
    assert res["статус"] == "not_found"


def test_archive_idempotent_returns_not_found_second_time(db_path: Path) -> None:
    """Повторный archive того же чанка → not_found (уже архивирован)."""
    added = tools.manager_memory_add(
        text="x", source="note", caller_role=_MD, db_path=db_path
    )
    cid = added["id"]
    tools.manager_memory_archive(chunk_id=cid, caller_role=_MD, db_path=db_path)
    res = tools.manager_memory_archive(
        chunk_id=cid, caller_role=_MD, db_path=db_path
    )
    assert res["статус"] == "not_found"


# === ROLE GATE — все 5 функций должны блокировать не-managing-director ===


def test_role_gate_add_backend_forbidden(db_path: Path) -> None:
    res = tools.manager_memory_add(
        text="попытка", source="note", caller_role="бэкенд", db_path=db_path
    )
    assert res["статус"] == "forbidden"
    assert _MD in res["причина"]


def test_role_gate_add_arhitector_forbidden(db_path: Path) -> None:
    res = tools.manager_memory_add(
        text="попытка", source="note", caller_role="архитектор", db_path=db_path
    )
    assert res["статус"] == "forbidden"


def test_role_gate_add_none_role_forbidden(db_path: Path) -> None:
    res = tools.manager_memory_add(
        text="попытка", source="note", caller_role=None, db_path=db_path
    )
    assert res["статус"] == "forbidden"


def test_role_gate_search_backend_forbidden(db_path: Path) -> None:
    res = tools.manager_memory_search(
        query="x", caller_role="бэкенд", db_path=db_path
    )
    assert res["статус"] == "forbidden"


def test_role_gate_get_qa_forbidden(db_path: Path) -> None:
    res = tools.manager_memory_get(chunk_id=1, caller_role="qa", db_path=db_path)
    assert res["статус"] == "forbidden"


def test_role_gate_recent_тимлид_forbidden(db_path: Path) -> None:
    res = tools.manager_memory_recent(caller_role="тимлид", db_path=db_path)
    assert res["статус"] == "forbidden"


def test_role_gate_archive_frontend_forbidden(db_path: Path) -> None:
    res = tools.manager_memory_archive(
        chunk_id=1, caller_role="frontend", db_path=db_path
    )
    assert res["статус"] == "forbidden"


def test_role_gate_does_not_leak_data_to_unauthorized(db_path: Path) -> None:
    """Даже если данные есть — другой роли возвращается forbidden без утечки."""
    added = tools.manager_memory_add(
        text="секрет", source="note", caller_role=_MD, db_path=db_path
    )
    cid = added["id"]
    # Не managing-director не получает данные:
    leaked = tools.manager_memory_get(
        chunk_id=cid, caller_role="бэкенд", db_path=db_path
    )
    assert leaked["статус"] == "forbidden"
    assert "чанк" not in leaked
    assert "text" not in str(leaked.get("причина", ""))


# === FTS-триггеры: обновление и удаление синхронизируют индекс ===


def test_archive_then_search_does_not_match(db_path: Path) -> None:
    """После archive чанк не находится поиском (фильтр archived_at IS NULL)."""
    a = tools.manager_memory_add(
        text="специфическийтекстААА уникальный маркер",
        source="note",
        caller_role=_MD,
        db_path=db_path,
    )
    res_before = tools.manager_memory_search(
        query="специфическийтекстААА", caller_role=_MD, db_path=db_path
    )
    assert res_before["всего"] == 1

    tools.manager_memory_archive(
        chunk_id=a["id"], caller_role=_MD, db_path=db_path
    )
    res_after = tools.manager_memory_search(
        query="специфическийтекстААА", caller_role=_MD, db_path=db_path
    )
    assert res_after["всего"] == 0

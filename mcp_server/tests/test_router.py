"""Тесты автороутера моделей (pride_tasks.router).

Покрываются:
  - `pick()` — все ветки выбора (пустая очередь, архитектура, destructive,
    тривиальные, дефолт sonnet, фильтр эпиков).
  - `pick_from_db()` — что выборка задач из БД корректно агрегирует статусы.
  - CLI `main()` — оба режима вывода (`pick`/`model-only`).
"""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from pride_tasks import db, router


def _t(title: str = "", desc: str = "", labels: list[str] | None = None) -> dict:
    return {"title": title, "description": desc, "labels": labels or []}


# === pick() — табличные кейсы ===


def test_pick_empty_queue_returns_haiku() -> None:
    decision = router.pick([])
    assert decision["model_alias"] == "haiku"
    assert decision["model_full"] == "claude-haiku-4-5"
    assert "очередь пустая" in decision["reason"]
    assert decision["counters"]["total_workable"] == 0


def test_pick_only_epics_returns_haiku() -> None:
    # Эпики не считаются рабочими задачами — тимлид их только декомпозирует.
    decision = router.pick([
        _t(title="E1: эпик", labels=["epic"]),
        _t(title="E2: эпик", labels=["epic"]),
    ])
    assert decision["model_alias"] == "haiku"
    assert decision["counters"]["total_workable"] == 0
    assert decision["counters"]["epics_filtered"] == 2


def test_pick_design_label_triggers_opus() -> None:
    decision = router.pick([
        _t(title="любой заголовок", labels=["design"]),
    ])
    assert decision["model_alias"] == "opus"
    assert decision["counters"]["architectural"] == 1


def test_pick_adr_label_triggers_opus() -> None:
    decision = router.pick([_t(title="что-то", labels=["adr"])])
    assert decision["model_alias"] == "opus"


def test_pick_architecture_label_triggers_opus() -> None:
    decision = router.pick([_t(title="что-то", labels=["architecture"])])
    assert decision["model_alias"] == "opus"


def test_pick_text_with_word_adr_does_not_trigger_opus() -> None:
    # Слово «ADR» в title/description не должно матчиться — только явный label.
    # Это типовой false positive: «реализуй endpoint по ADR-002» — обычный код, не дизайн.
    decision = router.pick([
        _t(title="Реализуй endpoint по ADR-002", desc="простая работа"),
    ])
    assert decision["model_alias"] == "sonnet"
    assert decision["counters"]["architectural"] == 0


def test_pick_destructive_label_returns_opus() -> None:
    # destructive (миграции, удаления) теперь → opus для аккуратности и доп. контроля.
    decision = router.pick([
        _t(title="миграция БД", labels=["destructive"]),
    ])
    assert decision["model_alias"] == "opus"
    assert decision["counters"]["has_destructive"] is True
    assert "destructive" in decision["reason"]


def test_pick_destructive_priority_over_architectural() -> None:
    # destructive проверяется первым — безопасность важнее.
    decision = router.pick([
        _t(title="x", labels=["destructive"]),
        _t(title="y", labels=["design"]),
    ])
    assert decision["model_alias"] == "opus"
    assert "destructive" in decision["reason"]


def test_pick_only_trivial_labels_return_haiku() -> None:
    decision = router.pick([
        _t(title="x", labels=["trivial"]),
        _t(title="y", labels=["chore"]),
    ])
    assert decision["model_alias"] == "haiku"
    assert decision["counters"]["trivial"] == 2


def test_pick_default_returns_sonnet() -> None:
    # Обычные задачи (код, документы) без архитектурных labels → sonnet.
    decision = router.pick([
        _t(title="реализуй фичу X", desc="обычный код"),
        _t(title="обнови README"),
        _t(title="добавь test_*"),
    ])
    assert decision["model_alias"] == "sonnet"
    assert decision["counters"]["architectural"] == 0
    assert decision["counters"]["total_workable"] == 3


def test_pick_filters_epics_keeps_children() -> None:
    decision = router.pick([
        _t(title="E1: эпик", labels=["epic"]),
        _t(title="E1.1 child task", labels=["E1"]),
        _t(title="E1.2 child task", labels=["E1"]),
    ])
    assert decision["model_alias"] == "sonnet"
    assert decision["counters"]["total_workable"] == 2
    assert decision["counters"]["epics_filtered"] == 1


def test_pick_counters_structure() -> None:
    decision = router.pick([_t(title="x")])
    counters = decision["counters"]
    for key in ("total_workable", "epics_filtered", "architectural",
                "trivial", "has_destructive"):
        assert key in counters


def test_pick_handles_missing_fields() -> None:
    decision = router.pick([{}])
    assert decision["model_alias"] in {"haiku", "sonnet", "opus"}


# === pick_from_db() ===


def test_pick_from_db_empty(db_path: Path) -> None:
    decision = router.pick_from_db(db_path)
    assert decision["model_alias"] == "haiku"
    assert decision["counters"]["total_workable"] == 0


def test_pick_from_db_aggregates_statuses(db_path: Path) -> None:
    # Создаём задачи в разных статусах — pick_from_db должен их все взять.
    db.insert_task(db_path, title="дизайн модуля", description="", labels=["design"])
    t2 = db.insert_task(db_path, title="обычная задача", description="")
    db.update_task(db_path, t2["id"], status="wip")
    t3 = db.insert_task(db_path, title="ревьюшная", description="")
    db.update_task(db_path, t3["id"], status="review")
    # done — не должна попасть
    t4 = db.insert_task(db_path, title="закрытая", description="")
    db.update_task(db_path, t4["id"], status="done")

    decision = router.pick_from_db(db_path)
    # Архитектурная по label → opus
    assert decision["model_alias"] == "opus"
    assert decision["counters"]["total_workable"] == 3


def test_pick_from_db_filters_epics(db_path: Path) -> None:
    db.insert_task(db_path, title="эпик", description="", labels=["epic"])
    db.insert_task(db_path, title="обычная", description="")
    decision = router.pick_from_db(db_path)
    assert decision["counters"]["total_workable"] == 1
    assert decision["counters"]["epics_filtered"] == 1


# === CLI main() ===


def test_main_pick_outputs_json(db_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PRIDE_TASKS_DB", str(db_path))
    monkeypatch.setattr(sys, "argv", ["router", "pick"])
    buf = io.StringIO()
    with redirect_stdout(buf):
        router.main()
    out = buf.getvalue()
    assert "model_alias" in out
    assert "counters" in out
    import json as _json
    parsed = _json.loads(out)
    assert parsed["model_alias"] in {"haiku", "sonnet", "opus"}


def test_main_model_only_outputs_alias(db_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PRIDE_TASKS_DB", str(db_path))
    monkeypatch.setattr(sys, "argv", ["router", "model-only"])
    buf = io.StringIO()
    with redirect_stdout(buf):
        router.main()
    out = buf.getvalue().strip()
    assert out in {"haiku", "sonnet", "opus"}


def test_main_invalid_action_exits(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["router", "wrong-action"])
    with pytest.raises(SystemExit):
        router.main()

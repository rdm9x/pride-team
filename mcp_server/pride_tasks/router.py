"""Авто-роутер моделей для запуска тимлида.

Решает какую Claude-модель использовать в следующей сессии тимлида,
исходя из открытых задач канбана. Алгоритмический (без LLM, без затрат
токенов), прозрачный — пользователь видит причину выбора.

Используется:
  - pride-team-work.sh: вызывает `python -m pride_tasks.router pick`,
    получает имя модели, передаёт в `claude --model`.
  - Дашборд: показывает текущую рекомендацию в плашке шапки
    (через REST endpoint /api/router/pick).

Принципы:
  - Дешевле = лучше. Если задача укладывается в Haiku — выбираем Haiku.
  - Архитектура, стратегия и destructive-операции требуют Opus.
  - Дефолт — Sonnet (код, документы, обычная разработка).
  - Классификация — только по labels (явный сигнал), не по keywords в title/description
    (там слишком много false positives — слово «ADR» в контексте «по ADR-002» делает
    обычную имплементацию ложно-архитектурной).
  - Родительские эпики (label `epic`) исключаются — тимлид их не «делает»,
    только декомпозирует/делегирует child-задачи.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Labels, которые помечают задачу как требующую Opus
_ARCHI_LABELS = {"design", "architecture", "adr"}
# Labels, помечающие тривиальные операции (мелкие правки, статусы, переименования)
_TRIVIAL_LABELS = {"trivial", "chore", "rename", "polish"}

_MODELS = {
    "haiku":  "claude-haiku-4-5",
    "sonnet": "claude-sonnet-4-5",
    "opus":   "claude-opus-4-7",
}


def pick(open_tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Вернуть решение о модели + объяснение.

    Args:
        open_tasks: задачи которые тимлид увидит (status in todo|wip|review|needs_approval).

    Returns:
        {model_alias, model_full, reason, counters}
    """
    # Отфильтровываем родительские эпики — тимлид их не выполняет, только использует как контейнер.
    workable = [t for t in open_tasks if "epic" not in (t.get("labels") or [])]

    n_total = len(workable)
    n_archi = 0
    n_trivial = 0
    has_destructive = False

    for t in workable:
        labels = set(t.get("labels") or [])
        if labels & _ARCHI_LABELS:
            n_archi += 1
        if labels & _TRIVIAL_LABELS:
            n_trivial += 1
        if "destructive" in labels:
            has_destructive = True

    n_epics_filtered = len(open_tasks) - n_total

    if n_total == 0:
        choice = "haiku"
        reason = "очередь пустая (без учёта эпиков) — Haiku хватит на чтение чата и закрытие сессии"
    elif has_destructive:
        choice = "opus"
        reason = "есть destructive operations — Opus для аккуратности и проверки"
    elif n_archi > 0:
        choice = "opus"
        reason = f"архитектурных задач (по label): {n_archi} — Opus для design/decomposition"
    elif n_trivial > 0 and n_trivial == n_total:
        choice = "haiku"
        reason = f"только тривиальные задачи: {n_trivial} — Haiku хватит"
    else:
        choice = "sonnet"
        reason = f"{n_total} задач (код/документы/обычная разработка) — Sonnet"

    return {
        "model_alias": choice,
        "model_full": _MODELS[choice],
        "reason": reason,
        "counters": {
            "total_workable": n_total,
            "epics_filtered": n_epics_filtered,
            "architectural": n_archi,
            "trivial": n_trivial,
            "has_destructive": has_destructive,
        },
    }


def pick_from_db(db_path: Path | None = None) -> dict[str, Any]:
    """Собрать список открытых задач из БД и принять решение."""
    from pride_tasks import db

    path = db_path or db.default_db_path()
    open_tasks = []
    for status in ("todo", "wip", "review", "needs_approval"):
        open_tasks.extend(db.list_tasks(path, status=status, limit=200))
    # Снимем дубли по id (для подстраховки)
    seen = set()
    unique = []
    for t in open_tasks:
        if t["id"] in seen:
            continue
        seen.add(t["id"])
        unique.append(t)
    return pick(unique)


def main() -> None:
    parser = argparse.ArgumentParser(description="pride-team model router")
    parser.add_argument("action", choices=["pick", "model-only"],
                        help="pick — JSON {model, reason, counters}; model-only — только имя alias (haiku/sonnet/opus)")
    args = parser.parse_args()
    decision = pick_from_db()
    if args.action == "model-only":
        sys.stdout.write(decision["model_alias"])
    else:
        sys.stdout.write(json.dumps(decision, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

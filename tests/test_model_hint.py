"""Тесты model_hint flow (B5 fix).

Проверяет что явный model_hint пользователя переопределяет дефолтную
модель роли и авто-детекцию по labels (ADR-006 §2.3, B5).

Кейсы:
  1. задача с model_hint=sonnet → router.pick() возвращает sonnet
  2. задача без model_hint → берётся дефолт (sonnet для обычных задач)
  3. задача с model_hint=opus → opus
"""

from __future__ import annotations

import sys
from pathlib import Path

# Добавляем mcp_server в путь для импорта devboard_tasks
_MCP_DIR = Path(__file__).resolve().parent.parent / "mcp_server"
if str(_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_MCP_DIR))

from devboard_tasks import router


def _task(title: str = "задача", model_hint: str | None = None, labels: list[str] | None = None) -> dict:
    return {"title": title, "labels": labels or [], "model_hint": model_hint}


# === Три обязательных кейса (acceptance criteria B5) ===


def test_model_hint_sonnet_returns_sonnet() -> None:
    """Задача с model_hint=sonnet → router.pick() должен вернуть sonnet.

    Это основной баг из B5: пользователь явно выбрал sonnet через UI,
    но роутер игнорировал hint и шёл на opus из-за других задач в очереди.
    """
    tasks = [_task(title="фича с явным sonnet", model_hint="sonnet")]
    decision = router.pick(tasks)
    assert decision["model_alias"] == "sonnet", (
        f"ожидали sonnet, получили {decision['model_alias']!r}; reason: {decision['reason']}"
    )
    assert "model_hint" in decision["reason"]
    assert decision["counters"]["hint_sonnet"] == 1


def test_no_model_hint_uses_default() -> None:
    """Задача без model_hint → дефолтный выбор роутера (sonnet для обычных задач)."""
    tasks = [_task(title="обычная задача", model_hint=None)]
    decision = router.pick(tasks)
    assert decision["model_alias"] == "sonnet", (
        f"ожидали sonnet (дефолт), получили {decision['model_alias']!r}"
    )
    assert decision["counters"]["hint_sonnet"] == 0
    assert decision["counters"]["hint_opus"] == 0
    assert decision["counters"]["hint_haiku"] == 0


def test_model_hint_opus_returns_opus() -> None:
    """Задача с model_hint=opus → router.pick() должен вернуть opus."""
    tasks = [_task(title="задача с явным opus", model_hint="opus")]
    decision = router.pick(tasks)
    assert decision["model_alias"] == "opus", (
        f"ожидали opus, получили {decision['model_alias']!r}; reason: {decision['reason']}"
    )
    assert "model_hint" in decision["reason"]
    assert decision["counters"]["hint_opus"] == 1


# === Дополнительные кейсы для уверенности в fix ===


def test_model_hint_sonnet_overrides_architectural_labels_in_queue() -> None:
    """B5 core scenario: задача с model_hint=sonnet + другие architectural задачи в очереди.

    До fix: n_archi > 0 срабатывал первым → opus.
    После fix: hint_max_alias проверяется раньше → sonnet.
    """
    tasks = [
        _task(title="моя задача c sonnet", model_hint="sonnet"),
        _task(title="чужая архитектурная задача", labels=["design"]),
    ]
    decision = router.pick(tasks)
    assert decision["model_alias"] == "sonnet", (
        f"model_hint=sonnet должен побеждать над architectural задачами в очереди; "
        f"получили {decision['model_alias']!r}, reason: {decision['reason']}"
    )


def test_destructive_still_overrides_model_hint() -> None:
    """destructive-label имеет наивысший приоритет — безопасность важнее пользовательского hint."""
    tasks = [_task(title="опасная задача", model_hint="haiku", labels=["destructive"])]
    decision = router.pick(tasks)
    assert decision["model_alias"] == "opus"
    assert "destructive" in decision["reason"]


def test_model_hint_haiku_explicit() -> None:
    """Задача с model_hint=haiku → router возвращает haiku."""
    tasks = [_task(title="маленькая задача", model_hint="haiku")]
    decision = router.pick(tasks)
    assert decision["model_alias"] == "haiku"
    assert decision["counters"]["hint_haiku"] == 1

"""Тесты для GET /api/stats/aggregates (задача S3.2)."""

from __future__ import annotations

import time


def test_stats_default_range_returns_200(client) -> None:
    """Endpoint возвращает 200 и все обязательные поля для диапазона 24h."""
    r = client.get("/api/stats/aggregates")
    assert r.status_code == 200
    j = r.get_json()
    required_keys = {
        "range", "sessions", "turns", "cost_usd",
        "files_changed", "lines_written", "chat_chars",
        "hours_worked", "models", "roles", "hourly_activity", "top",
    }
    assert required_keys <= set(j.keys()), f"Отсутствуют ключи: {required_keys - set(j.keys())}"
    assert j["range"] == "24h"
    # top — вложенный словарь с обязательными ключами
    top_keys = {"longest_turn", "most_expensive_day", "fastest_task", "most_productive_role"}
    assert top_keys <= set(j["top"].keys())


def test_stats_all_ranges_return_200(client) -> None:
    """Все 4 диапазона отвечают 200."""
    for rng in ("today", "24h", "week", "all"):
        r = client.get(f"/api/stats/aggregates?range={rng}")
        assert r.status_code == 200, f"range={rng} вернул {r.status_code}"
        j = r.get_json()
        assert j["range"] == rng, f"range в ответе не совпадает для range={rng}"


def test_stats_hourly_activity_has_24_items(client) -> None:
    """hourly_activity содержит ровно 24 элемента (часы 0-23)."""
    r = client.get("/api/stats/aggregates?range=all")
    assert r.status_code == 200
    activity = r.get_json()["hourly_activity"]
    assert len(activity) == 24, f"Ожидалось 24, получено {len(activity)}"
    hours = [item["hour"] for item in activity]
    assert hours == list(range(24)), "Часы должны идти от 0 до 23"


def test_stats_with_sessions(client) -> None:
    """Endpoint корректно считает sessions/turns/cost из записанных сессий."""
    from pride_tasks import db as _db  # type: ignore

    db_path = client.application.config["DB_PATH"]
    now = int(time.time())
    _db.record_claude_session(
        db_path,
        started_at=now - 300,
        finished_at=now - 60,
        duration_ms=240_000,
        num_turns=12,
        input_tokens=5000,
        output_tokens=1500,
        total_cost_usd=0.055,
        model="claude-sonnet-4-6",
    )
    _db.record_claude_session(
        db_path,
        started_at=now - 600,
        finished_at=now - 400,
        duration_ms=200_000,
        num_turns=8,
        input_tokens=3000,
        output_tokens=900,
        total_cost_usd=0.030,
        model="claude-sonnet-4-6",
    )

    r = client.get("/api/stats/aggregates?range=24h")
    assert r.status_code == 200
    j = r.get_json()
    assert j["sessions"] == 2
    assert j["turns"] == 20
    assert abs(j["cost_usd"] - 0.085) < 0.001
    assert len(j["models"]) >= 1
    assert j["models"][0]["model"] == "claude-sonnet-4-6"
    assert j["models"][0]["sessions"] == 2


def test_stats_invalid_range_falls_back_to_24h(client) -> None:
    """Неизвестный range → дефолт 24h."""
    r = client.get("/api/stats/aggregates?range=bogus")
    assert r.status_code == 200
    assert r.get_json()["range"] == "24h"


def test_stats_cache_works(client) -> None:
    """Два быстрых запроса используют кэш (одинаковый ответ, оба 200)."""
    r1 = client.get("/api/stats/aggregates?range=week")
    r2 = client.get("/api/stats/aggregates?range=week")
    assert r1.status_code == 200
    assert r2.status_code == 200
    # Данные идентичны (взяты из кэша)
    assert r1.get_json() == r2.get_json()


def test_stats_all_models_shown_including_haiku(client) -> None:
    """S5.1: все модели (haiku/sonnet/opus) отображаются, включая с малыми затратами.

    Проверяет что claude-haiku-4-5-20251001 отображается на Statistics tab
    несмотря на очень малые затраты ($0.001) по сравнению с другими моделями.
    """
    from pride_tasks import db as _db  # type: ignore

    db_path = client.application.config["DB_PATH"]
    now = int(time.time())

    # Создаём 3 сессии с разными моделями и реалистичными затратами:
    # - Haiku: много сессий но малые затраты (как в реальности)
    # - Sonnet: средние затраты
    # - Opus: дорогие затраты

    _db.record_claude_session(
        db_path,
        started_at=now - 1000,
        finished_at=now - 950,
        duration_ms=50_000,
        num_turns=2,
        input_tokens=100,
        output_tokens=50,
        total_cost_usd=0.0003,  # Haiku очень дешёвый
        model="claude-haiku-4-5-20251001",
    )

    _db.record_claude_session(
        db_path,
        started_at=now - 900,
        finished_at=now - 850,
        duration_ms=50_000,
        num_turns=3,
        input_tokens=500,
        output_tokens=200,
        total_cost_usd=0.010,  # Sonnet дороже
        model="claude-sonnet-4-6",
    )

    _db.record_claude_session(
        db_path,
        started_at=now - 800,
        finished_at=now - 750,
        duration_ms=50_000,
        num_turns=5,
        input_tokens=2000,
        output_tokens=1000,
        total_cost_usd=0.150,  # Opus самый дорогой
        model="claude-opus-4-7",
    )

    r = client.get("/api/stats/aggregates?range=all")
    assert r.status_code == 200, f"endpoint вернул {r.status_code}: {r.get_data(as_text=True)}"
    j = r.get_json()

    # Проверяем что ВСЕ модели присутствуют в ответе
    model_names = [m["model"] for m in j["models"]]
    assert "claude-haiku-4-5-20251001" in model_names, f"haiku отсутствует в models: {model_names}"
    assert "claude-sonnet-4-6" in model_names, f"sonnet отсутствует в models: {model_names}"
    assert "claude-opus-4-7" in model_names, f"opus отсутствует в models: {model_names}"
    assert len(model_names) == 3, f"Ожидалось 3 модели, получено {len(model_names)}: {model_names}"

    # Проверяем что Haiku на месте с правильной статистикой (даже если стоит последним)
    haiku = next((m for m in j["models"] if m["model"] == "claude-haiku-4-5-20251001"), None)
    assert haiku is not None, "Haiku не найден в списке моделей"
    assert haiku["sessions"] == 1
    assert haiku["cost_usd"] == 0.0003
    assert haiku["input_tokens"] == 100
    assert haiku["output_tokens"] == 50

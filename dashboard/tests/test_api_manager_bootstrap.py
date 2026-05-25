"""Тесты GET /api/manager/bootstrap (B4, ADR-007 §2.4 + ADR-009 §2.2).

Покрывает:
  - 200 + JSON с 6 ожидаемыми полями.
  - inboxes: list[dict], dept_id/wip/review/blocked/last_chat_msg_time валидны.
  - chat_recent: list, только глобальные (department_id IS NULL), <=50, в
    хронологическом порядке.
  - adr_list: парсер находит реальные docs/adr/*.md (9 файлов на дату B4),
    у каждого number/title/file заполнены.
  - memory_notes возвращает только source='note', memory_recall — только 'recall'.
  - planning_sessions_active не включает phase='done', но включает phase='gathering' и
    'discussion'.
  - Производительность: ответ <500ms (мягкая проверка, локальная БД).
"""

from __future__ import annotations

import time


# === helpers ===


def _post_chat(client, text: str, *, department: str = "__global__") -> None:
    """Постит сообщение через REST (нет прямого db.post_chat_message в тестах)."""
    r = client.post(f"/api/chat?department={department}", json={"author": "пользователь", "text": text})
    assert r.status_code == 201, r.get_data(as_text=True)


def _create_dept(client, name: str) -> str:
    r = client.post("/api/departments", json={"name": name})
    assert r.status_code == 201, r.get_data(as_text=True)
    return r.get_json()["department"]["id"]


def _db_path(client):
    return client.application.config["DB_PATH"]


def _db_module():
    """Ленивый импорт devboard_tasks.db — conftest.py + app.py добавляют его в sys.path."""
    from devboard_tasks import db as _db  # noqa: PLC0415

    return _db


# === happy path: структура ответа ===


def test_bootstrap_returns_200_and_six_fields(client) -> None:
    """Endpoint существует, отдаёт 200 и JSON с 6 обязательными полями."""
    r = client.get("/api/manager/bootstrap")
    assert r.status_code == 200, r.get_data(as_text=True)
    data = r.get_json()
    assert isinstance(data, dict)
    expected_fields = {
        "inboxes",
        "chat_recent",
        "adr_list",
        "memory_notes",
        "memory_recall",
        "planning_sessions_active",
    }
    assert set(data.keys()) == expected_fields, (
        f"ожидалось ровно 6 полей; получено: {set(data.keys())}"
    )


def test_bootstrap_field_types(client) -> None:
    """Каждое из 6 полей валидного типа (все — list)."""
    r = client.get("/api/manager/bootstrap")
    data = r.get_json()
    for field in (
        "inboxes",
        "chat_recent",
        "adr_list",
        "memory_notes",
        "memory_recall",
        "planning_sessions_active",
    ):
        assert isinstance(data[field], list), (
            f"поле {field!r} должно быть list; получено {type(data[field]).__name__}"
        )


# === inboxes ===


def test_bootstrap_inboxes_contains_dev_department(client) -> None:
    """init_db создаёт дефолтный 'dev' — он должен быть в inboxes."""
    r = client.get("/api/manager/bootstrap")
    inboxes = r.get_json()["inboxes"]
    dept_ids = {entry["dept_id"] for entry in inboxes}
    assert "dev" in dept_ids, f"ожидался dev в inboxes; получено: {dept_ids}"
    # Каждый entry имеет ключи из inbox_summary
    for entry in inboxes:
        assert set(entry.keys()) >= {
            "dept_id", "dept_name", "wip", "review", "blocked", "last_chat_msg_time"
        }, f"некомплект ключей в inbox-entry: {entry}"
        assert isinstance(entry["wip"], int)
        assert isinstance(entry["review"], int)
        assert isinstance(entry["blocked"], int)


def test_bootstrap_inboxes_reflects_new_department(client) -> None:
    """После create_department новый dept появляется в inboxes."""
    dept = _create_dept(client, "Marketing")
    r = client.get("/api/manager/bootstrap")
    inboxes = r.get_json()["inboxes"]
    dept_ids = {entry["dept_id"] for entry in inboxes}
    assert dept in dept_ids


# === chat_recent ===


def test_bootstrap_chat_recent_only_global_channel(client) -> None:
    """В chat_recent попадают только department_id IS NULL сообщения."""
    # Постим 2 в глобальный + 1 в dev
    _post_chat(client, "global #1", department="__global__")
    _post_chat(client, "global #2", department="__global__")
    _post_chat(client, "dev-only message", department="dev")

    r = client.get("/api/manager/bootstrap")
    chat = r.get_json()["chat_recent"]
    texts = [m["text"] for m in chat]
    assert "global #1" in texts
    assert "global #2" in texts
    assert "dev-only message" not in texts
    # У всех department_id is None
    for m in chat:
        assert m["department_id"] is None


def test_bootstrap_chat_recent_limit_50_and_chronological(client) -> None:
    """Возвращается не больше 50 сообщений, в хронологическом порядке (id ASC)."""
    # Постим 55 — должны увидеть последние 50, в порядке от старых к новым
    for i in range(55):
        _post_chat(client, f"msg-{i:03d}", department="__global__")

    r = client.get("/api/manager/bootstrap")
    chat = r.get_json()["chat_recent"]
    assert len(chat) == 50, f"ожидалось 50 сообщений; получено {len(chat)}"
    # Самое старое в выборке — msg-005 (первые 5 «срезаны»), самое новое — msg-054
    assert chat[0]["text"] == "msg-005"
    assert chat[-1]["text"] == "msg-054"
    # id монотонно возрастают
    ids = [m["id"] for m in chat]
    assert ids == sorted(ids), "chat_recent должен быть в хронологическом порядке"


# === adr_list ===


def test_bootstrap_adr_list_finds_real_adrs(client) -> None:
    """Парсер находит реальные docs/adr/*.md (на дату B4 — 9 файлов)."""
    r = client.get("/api/manager/bootstrap")
    adrs = r.get_json()["adr_list"]
    # Минимум 9 ADR (0001..0009 уже в репо)
    assert len(adrs) >= 9, f"ожидалось >= 9 ADR; нашли {len(adrs)}"
    # У каждого number, title, file заполнены
    for entry in adrs:
        assert "number" in entry and "title" in entry and "status" in entry and "file" in entry
        assert entry["file"].endswith(".md")
        # number может быть int (для нормальных ADR-NNNN-*.md)
        if entry["number"] is not None:
            assert isinstance(entry["number"], int)
    # Конкретно проверяем что ADR-007 и ADR-009 распознаны
    numbers = {a["number"] for a in adrs}
    assert 7 in numbers, "ADR-007 (memory-layer) не распознан"
    assert 9 in numbers, "ADR-009 (managing-director) не распознан"

    # Заголовки парсятся
    by_num = {a["number"]: a for a in adrs if a["number"] is not None}
    adr_009 = by_num[9]
    assert adr_009["title"]  # not empty
    assert "Управляющий" in adr_009["title"] or "managing" in adr_009["title"].lower()
    # Статус ADR-009 на момент B4: "Proposed (2026-05-25, rev 2 ...)"
    assert adr_009["status"] is not None
    assert "Proposed" in adr_009["status"] or "Accepted" in adr_009["status"] or "Revised" in adr_009["status"]


def test_bootstrap_adr_list_sorted_by_number(client) -> None:
    """ADR'ы отсортированы по номеру по возрастанию."""
    r = client.get("/api/manager/bootstrap")
    adrs = r.get_json()["adr_list"]
    numbers = [a["number"] for a in adrs if a["number"] is not None]
    assert numbers == sorted(numbers), f"adr_list не отсортирован: {numbers}"


# === memory_notes / memory_recall ===


def test_bootstrap_memory_notes_only_source_note(client) -> None:
    """memory_notes содержит только source='note'."""
    db_path = _db_path(client)
    _db = _db_module()
    _db.manager_chunk_insert(db_path, text="note-A", source="note")
    _db.manager_chunk_insert(db_path, text="note-B", source="note")
    _db.manager_chunk_insert(db_path, text="recall-X", source="recall")
    _db.manager_chunk_insert(db_path, text="conv-Y", source="conversation")

    r = client.get("/api/manager/bootstrap")
    notes = r.get_json()["memory_notes"]
    texts = [n["text"] for n in notes]
    assert "note-A" in texts
    assert "note-B" in texts
    assert "recall-X" not in texts
    assert "conv-Y" not in texts
    for n in notes:
        assert n["source"] == "note"


def test_bootstrap_memory_recall_only_source_recall(client) -> None:
    """memory_recall содержит только source='recall'."""
    db_path = _db_path(client)
    _db = _db_module()
    _db.manager_chunk_insert(db_path, text="recall-1", source="recall")
    _db.manager_chunk_insert(db_path, text="recall-2", source="recall")
    _db.manager_chunk_insert(db_path, text="note-Z", source="note")

    r = client.get("/api/manager/bootstrap")
    recall = r.get_json()["memory_recall"]
    texts = [n["text"] for n in recall]
    assert "recall-1" in texts
    assert "recall-2" in texts
    assert "note-Z" not in texts
    for n in recall:
        assert n["source"] == "recall"


def test_bootstrap_memory_recall_limit_10(client) -> None:
    """memory_recall ограничен 10 элементами."""
    db_path = _db_path(client)
    _db = _db_module()
    for i in range(15):
        _db.manager_chunk_insert(db_path, text=f"r-{i}", source="recall")
    r = client.get("/api/manager/bootstrap")
    recall = r.get_json()["memory_recall"]
    assert len(recall) == 10, f"ожидалось 10 элементов recall; получено {len(recall)}"


def test_bootstrap_memory_notes_limit_20(client) -> None:
    """memory_notes ограничен 20 элементами."""
    db_path = _db_path(client)
    _db = _db_module()
    for i in range(25):
        _db.manager_chunk_insert(db_path, text=f"n-{i}", source="note")
    r = client.get("/api/manager/bootstrap")
    notes = r.get_json()["memory_notes"]
    assert len(notes) == 20, f"ожидалось 20 элементов notes; получено {len(notes)}"


# === planning_sessions_active ===


def test_bootstrap_planning_sessions_excludes_done(client) -> None:
    """planning_sessions_active не содержит phase='done'."""
    db_path = _db_path(client)
    _db = _db_module()
    # Создаём 3 сессии: gathering, discussion, done.
    s1 = _db.planning_session_create(
        db_path, owner_request="active gathering", departments=["dev"], phase="gathering"
    )
    s2 = _db.planning_session_create(
        db_path, owner_request="active discussion", departments=["dev"]
    )
    _db.planning_session_update(db_path, s2["id"], phase="discussion")
    s3 = _db.planning_session_create(
        db_path, owner_request="finished session", departments=["dev"]
    )
    _db.planning_session_update(db_path, s3["id"], phase="done", finished_at=int(time.time()))

    r = client.get("/api/manager/bootstrap")
    active = r.get_json()["planning_sessions_active"]
    ids = {s["id"] for s in active}
    assert s1["id"] in ids
    assert s2["id"] in ids
    assert s3["id"] not in ids, "done-сессия не должна попадать в active"
    # Все возвращённые имеют phase != 'done'
    for s in active:
        assert s["phase"] != "done"


def test_bootstrap_planning_sessions_empty_by_default(client) -> None:
    """Свежая БД — пустой planning_sessions_active."""
    r = client.get("/api/manager/bootstrap")
    assert r.get_json()["planning_sessions_active"] == []


# === производительность ===


def test_bootstrap_response_time_under_500ms(client) -> None:
    """Время ответа < 500ms на пустой/нормальной БД (мягкая проверка)."""
    # Прогрев — первый запрос инициализирует роуты.
    client.get("/api/manager/bootstrap")
    t0 = time.perf_counter()
    r = client.get("/api/manager/bootstrap")
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert r.status_code == 200
    # Запас по верхней границе — на CI бывает медленнее, поэтому держим 500ms цель.
    assert elapsed_ms < 500, f"bootstrap занял {elapsed_ms:.0f}ms (цель <500ms)"

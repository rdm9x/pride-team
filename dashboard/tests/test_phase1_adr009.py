"""Q1: E2E тесты Phase 1 ADR-009 (managing-director + memory).

Source-of-truth:
  - docs/adr/0009-managing-director.md §11 (Q1-Q5 acceptance)
  - docs/adr/0007-memory-layer.md (memory tests)

Покрывает 6 сценариев:
  1. Default flow (без планёрки) — Управляющий создаёт cross-task в dev напрямую,
     dev-lead/legacy-тимлид подхватывает, ведёт через статусы → review.
  2. Planning flow — start → collect → finalize, planning_sessions.phase
     progressирует gathering → discussion → done, cross-task создаётся.
  3. Memory — manager_memory_add → search → recent (sorted updated_at DESC).
  4. Role gate — manager_memory_add из роли != managing-director → 403,
     планёрочные tools тоже отбивают чужих.
  5. Migration regression — legacy assignee='тимлид' создаёт задачу/claim,
     list_roles() возвращает 'тимлид' (canonical name; в боевой БД slug='dev-lead').
  6. End-to-end bonus — owner → planning → consolidation → distribution → claim →
     review с полным прогрессом фаз planning_sessions.

Тесты НЕ запускают реальный claude-cli (это интеграция Управляющего как Claude-
сессии). Вместо этого вызываем MCP-tools от имени caller_role='managing-director' —
эквивалент того что делает Claude-сессия Управляющего через MCP-протокол.

Тестовый стиль:
  - используем dashboard `client` fixture (создаёт изолированную tmp_path БД),
  - DB_PATH вытаскиваем из client.application.config — это путь к свежей БД,
  - вызываем tools.* напрямую (как делают test_stats_endpoint.py и test_v2_e2e.py).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

# Гарантируем что mcp_server/ в sys.path для импорта pride_tasks.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_MCP_DIR = _REPO_ROOT / "mcp_server"
if str(_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_MCP_DIR))


_MD = "managing-director"


# === Утилиты ===


def _db_path(client) -> Path:
    """Достаёт путь к тестовой БД из Flask-конфига."""
    return Path(client.application.config["DB_PATH"])


def _create_dept(db_path: Path, slug: str, name: str) -> str:
    """Создаёт отдел напрямую через db (минуя HR-pipeline)."""
    from pride_tasks import db as _db  # type: ignore

    d = _db.create_department(db_path, dept_id=slug, name=name)
    return d["id"]


# === 1. Default flow (без планёрки) ===


def test_default_flow_managing_director_direct_cross_task(client) -> None:
    """Default flow: owner пишет про баг → Управляющий создаёт задачу в dev напрямую.

    Имитация: вместо запуска живого Управляющего вызываем MCP-tool create_task
    с reporter='managing-director' (как делает finalize_planning_session,
    но без планёрки). НЕТ planning_sessions row — это и есть default flow.
    """
    from pride_tasks import db as _db, tools  # type: ignore

    db_path = _db_path(client)

    # Owner пишет в общий чат.
    _db.post_chat_message(
        db_path,
        "пользователь",
        "пофиксь баг X в dev — UI ломается на пустом title",
        department_id=None,
    )

    # Управляющий распределяет задачу напрямую в dev (без планёрки).
    res = tools.create_task(
        title="Фикс UI на пустом title",
        description="Owner сообщил: UI ломается когда title пустой.",
        reporter="managing-director",
        priority="P2",
        department_id="dev",
        labels=["from-managing-director"],
        db_path=db_path,
    )
    assert res["статус"] == "ok"
    task = res["задача"]
    task_id = task["id"]
    assert task["department_id"] == "dev"
    assert task["status"] == "todo"
    assert task["assignee"] is None

    # Проверяем что planning_sessions row НЕТ.
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    try:
        n = conn.execute("SELECT COUNT(*) FROM planning_sessions").fetchone()[0]
        assert n == 0, "default flow не должен создавать planning_sessions row"
    finally:
        conn.close()

    # Тимлид (legacy assignee) подхватывает.
    claim_res = tools.claim_task(task_id, assignee="тимлид", db_path=db_path)
    assert claim_res["статус"] == "ok"
    assert claim_res["задача"]["assignee"] == "тимлид"

    # Переводит в review (safety-net блокирует done через MCP).
    upd = tools.update_task(task_id, status="review", db_path=db_path)
    assert upd["статус"] == "ok"
    assert upd["задача"]["status"] == "review"


# === 2. Planning flow ===


def test_planning_flow_full_progression(client) -> None:
    """Planning flow: gathering → discussion → done.

    Phase 3 (consolidation) — Claude-уровневое решение Управляющего,
    отдельного MCP-tool под неё нет (см. ADR-009 §2.6 — только 4 tools).
    """
    from pride_tasks import db as _db, tools  # type: ignore

    db_path = _db_path(client)

    # Phase 1: start_planning_session
    start = tools.start_planning_session(
        owner_request="рефакторинг архитектуры роутера моделей",
        departments=["dev"],
        caller_role=_MD,
        db_path=db_path,
    )
    assert start["статус"] == "ok"
    sid = start["session_id"]
    assert start["сессия"]["phase"] == "gathering"

    # В чате dev появилось приглашение от Управляющего.
    msgs = _db.list_chat_messages(db_path, department_id="dev", limit=10)
    md_msgs = [m for m in msgs if m["author"] == "managing-director"]
    assert len(md_msgs) >= 1
    assert "Планёрка" in md_msgs[0]["text"]

    # Эмулируем ответ dev-lead — legacy author=тимлид (см. ADR-009 §6.5 backward-compat).
    time.sleep(1.01)  # secund-grained ts
    _db.post_chat_message(
        db_path,
        "тимлид",
        "уточни какие части роутера трогаем — модель-выбор или фолбэки?",
        department_id="dev",
    )

    # Phase 2: collect_planning_responses
    collect = tools.collect_planning_responses(sid, caller_role=_MD, db_path=db_path)
    assert collect["статус"] == "ok"
    log = collect["discussion_log"]
    # Реплика лида попала в лог, приглашение Управляющего — нет.
    assert len(log) >= 1
    assert any("уточни" in r["text"] for r in log)
    assert all(r["author"] != "managing-director" for r in log)
    # Phase обновился.
    assert collect["сессия"]["phase"] == "discussion"
    assert _db.planning_session_get(db_path, sid)["phase"] == "discussion"

    # Phase 4: finalize_planning_session (owner ответил)
    owner_answer = (
        "dev: переписать только селектор модели — фолбэки оставить как есть.\n"
        "Приоритет P1, есть смежные правки в роутере."
    )
    final = tools.finalize_planning_session(
        sid, owner_answer, caller_role=_MD, db_path=db_path
    )
    assert final["статус"] == "ok"
    assert final["status"] == "done"
    created = final["created_tasks"]
    assert len(created) == 1
    assert created[0]["dept"] == "dev"
    task_id = created[0]["task_id"]

    # Задача создана с правильным метатэгом.
    task = _db.get_task(db_path, task_id)
    assert task is not None
    assert task["department_id"] == "dev"
    assert task["requester_role_slug"] == "managing-director"
    assert task["requester_department_id"] is None
    assert "planning:" in " ".join(task["labels"])
    assert "from-planning" in task["labels"]

    # Session завершена.
    final_session = _db.planning_session_get(db_path, sid)
    assert final_session["phase"] == "done"
    assert final_session["finished_at"] is not None
    assert final_session["owner_answer"] == owner_answer
    assert len(final_session["created_tasks"]) == 1


# === 3. Memory: add / search / recent ===


def test_memory_add_search_recent(client) -> None:
    """manager_memory_add → search находит → recent сортирует по updated_at DESC."""
    from pride_tasks import tools  # type: ignore

    db_path = _db_path(client)

    a = tools.manager_memory_add(
        text="Owner предпочитает короткие ответы без воды",
        source="note",
        tags=["owner", "preferences"],
        caller_role=_MD,
        db_path=db_path,
    )
    assert a["статус"] == "ok"
    assert a["id"] > 0

    time.sleep(1.05)  # SQLite seconds-grain, гарантируем разные updated_at

    b = tools.manager_memory_add(
        text="Менеджер запомнил: рефакторинг роутера в Phase 2",
        source="recall",
        caller_role=_MD,
        db_path=db_path,
    )
    assert b["статус"] == "ok"

    # Search по уникальному русскому токену
    s = tools.manager_memory_search(
        query="рефакторинг", caller_role=_MD, db_path=db_path
    )
    assert s["статус"] == "ok"
    assert s["всего"] >= 1
    assert any("рефакторинг" in r["text"].lower() for r in s["результаты"])

    # Recent: последний созданный — первым.
    r = tools.manager_memory_recent(caller_role=_MD, db_path=db_path)
    assert r["статус"] == "ok"
    assert r["всего"] == 2
    assert r["чанки"][0]["id"] == b["id"]
    assert r["чанки"][1]["id"] == a["id"]

    # Filter по source.
    only_notes = tools.manager_memory_recent(
        source="note", caller_role=_MD, db_path=db_path
    )
    assert only_notes["всего"] == 1
    assert only_notes["чанки"][0]["source"] == "note"
    assert only_notes["чанки"][0]["id"] == a["id"]


# === 4. Role gate ===


def test_role_gate_blocks_non_managing_director(client) -> None:
    """Memory + planning tools отбивают не-managing-director ролей с forbidden."""
    from pride_tasks import tools  # type: ignore

    db_path = _db_path(client)

    # manager_memory_add — отбивает все варианты non-MD.
    for role in ("бэкенд", "qa", "архитектор", "тимлид", "dev-lead", None):
        res = tools.manager_memory_add(
            text="попытка записать", source="note",
            caller_role=role, db_path=db_path,
        )
        assert res["статус"] == "forbidden", f"role={role!r}"
        assert "managing-director" in res["причина"]

    # search/get/recent/archive — те же 403 для не-MD.
    assert tools.manager_memory_search(
        query="x", caller_role="бэкенд", db_path=db_path
    )["статус"] == "forbidden"
    assert tools.manager_memory_get(
        chunk_id=1, caller_role="qa", db_path=db_path
    )["статус"] == "forbidden"
    assert tools.manager_memory_recent(
        caller_role="frontend", db_path=db_path
    )["статус"] == "forbidden"
    assert tools.manager_memory_archive(
        chunk_id=1, caller_role="devops", db_path=db_path
    )["статус"] == "forbidden"

    # Planning tools — тоже под role gate.
    assert tools.list_all_inboxes(
        caller_role="бэкенд", db_path=db_path
    )["статус"] == "forbidden"
    assert tools.start_planning_session(
        "x", ["dev"], caller_role="тимлид", db_path=db_path
    )["статус"] == "forbidden"
    assert tools.collect_planning_responses(
        "deadbeef0000", caller_role="qa", db_path=db_path
    )["статус"] == "forbidden"
    assert tools.finalize_planning_session(
        "deadbeef0000", "ответ", caller_role="frontend", db_path=db_path
    )["статус"] == "forbidden"


def test_role_gate_does_not_leak_data(client) -> None:
    """Чужая роль не должна получать содержимое чанка через forbidden-ответ."""
    from pride_tasks import tools  # type: ignore

    db_path = _db_path(client)
    secret = "секретный_текст_только_для_управляющего_xyz123"
    added = tools.manager_memory_add(
        text=secret, source="note", caller_role=_MD, db_path=db_path
    )
    assert added["статус"] == "ok"
    cid = added["id"]

    # Не-MD не получает данные:
    leaked = tools.manager_memory_get(
        chunk_id=cid, caller_role="бэкенд", db_path=db_path
    )
    assert leaked["статус"] == "forbidden"
    assert "чанк" not in leaked
    # Текст в текст ответа не утёк.
    blob = repr(leaked)
    assert secret not in blob


# === 5. Migration regression: legacy assignee=тимлид ===


def test_migration_legacy_тимлид_still_works(client) -> None:
    """A2 переименовала slug='dev-lead', но legacy name='тимлид' (PK) сохранён.

    Backward-compat (ADR-009 §6.5): задачи с assignee='тимлид' создаются,
    выводятся, и тимлид может их claim-нуть. Это критично потому что в БД
    есть 41 task'а с assignee='тимлид' (см. result задачи #943b5dd1ec14).
    """
    from pride_tasks import tools  # type: ignore

    db_path = _db_path(client)

    # 1) create_task с assignee='тимлид' проходит ROLES whitelist (см. models.ROLES).
    res = tools.create_task(
        title="legacy задача для тимлида",
        assignee="тимлид",
        department_id="dev",
        priority="P2",
        db_path=db_path,
    )
    assert res["статус"] == "ok"
    tid = res["задача"]["id"]
    assert res["задача"]["assignee"] == "тимлид"

    # 2) задача видна в outbox/list_tasks с фильтром.
    listing = tools.list_tasks(assignee="тимлид", db_path=db_path)
    assert listing["статус"] == "ok"
    assert any(t["id"] == tid for t in listing["задачи"])

    # 3) тимлид может claim'нуть задачу без assignee.
    res2 = tools.create_task(
        title="новая задача без assignee",
        department_id="dev",
        priority="P2",
        db_path=db_path,
    )
    tid2 = res2["задача"]["id"]
    assert res2["задача"]["assignee"] is None
    claim = tools.claim_task(tid2, assignee="тимлид", db_path=db_path)
    assert claim["статус"] == "ok"
    assert claim["задача"]["assignee"] == "тимлид"


def test_list_roles_uses_dev_lead_name(client) -> None:
    """ADR-009 Phase 1.7: после миграции роль называется 'dev-lead', а не 'тимлид'.

    Этот тест ранее проверял что legacy 'тимлид' остаётся для backward compat,
    но после полной миграции (scripts/migrate_тимлид_to_dev_lead.py) — `тимлид`
    исчезает из БД, остаётся только `dev-lead`.
    """
    from pride_tasks import tools  # type: ignore

    db_path = _db_path(client)
    roles_res = tools.list_roles(db_path=db_path)
    assert roles_res["статус"] == "ok"
    names = {r["name"] for r in roles_res["роли"]}
    # После Phase 1.7 миграции — dev-lead, не тимлид.
    assert "dev-lead" in names, (
        f"роль 'dev-lead' должна быть после миграции. Получено: {names}"
    )
    assert "тимлид" not in names, (
        f"legacy 'тимлид' должен исчезнуть после полной миграции. Получено: {names}"
    )


def test_live_db_has_dev_lead_slug_after_a2() -> None:
    """Если в боевой БД присутствует колонка slug — для записи name='тимлид'
    значение slug должно быть 'dev-lead' (результат A2 миграции).

    Тест мягкий: если боевой БД нет (CI / свежий клон) — skip.
    """
    live_db = Path(__file__).resolve().parents[2] / "data" / "tasks.db"
    if not live_db.exists():
        pytest.skip("боевой data/tasks.db не найден (свежее окружение)")

    import sqlite3
    conn = sqlite3.connect(str(live_db))
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(roles)")}
        if "slug" not in cols:
            pytest.skip(
                "в боевой БД нет колонки roles.slug — A2 миграция ещё не выполнена"
            )
        row = conn.execute(
            "SELECT slug FROM roles WHERE name = 'тимлид'"
        ).fetchone()
        # Если name='тимлид' нет — A2 уже сделала ренейм name (но это не наш кейс по плану A2).
        if row is None:
            pytest.skip("в боевой БД нет name='тимлид' — другая ветка миграции")
        assert row[0] == "dev-lead", (
            f"роль с name='тимлид' должна иметь slug='dev-lead' после A2, "
            f"получено: {row[0]!r}"
        )
    finally:
        conn.close()


# === 6. Bonus: full E2E owner → planning → consolidation → distribution → review ===


def test_full_e2e_owner_planning_to_review(client) -> None:
    """End-to-end один тест: owner → planning → consolidation → distribution →
    legacy-тимлид подхватывает → review. Проверяем прогресс фаз planning_sessions.
    """
    from pride_tasks import db as _db, tools  # type: ignore

    db_path = _db_path(client)

    # Owner шлёт сигнал в общий чат — Управляющий читает.
    _db.post_chat_message(
        db_path,
        "пользователь",
        "нужна планёрка: переход на новые модели роутера",
        department_id=None,
    )

    # Управляющий стартует планёрку для dev.
    start = tools.start_planning_session(
        "переход на новые модели роутера", ["dev"],
        caller_role=_MD, db_path=db_path,
    )
    sid = start["session_id"]
    assert _db.planning_session_get(db_path, sid)["phase"] == "gathering"

    # dev-lead (тимлид) пишет вопрос.
    time.sleep(1.01)
    _db.post_chat_message(
        db_path, "тимлид", "Сколько моделей трогаем? Только Sonnet или все три?",
        department_id="dev",
    )

    # Управляющий собирает реплики.
    collect = tools.collect_planning_responses(
        sid, caller_role=_MD, db_path=db_path
    )
    assert collect["статус"] == "ok"
    assert len(collect["discussion_log"]) == 1
    assert _db.planning_session_get(db_path, sid)["phase"] == "discussion"

    # Управляющий записывает консолидированную заметку в память.
    note = tools.manager_memory_add(
        text="Owner: переход на новые модели, dev спрашивает scope (Sonnet vs все 3).",
        source="planning",
        path=f"planning_session/{sid}",
        caller_role=_MD,
        db_path=db_path,
    )
    assert note["статус"] == "ok"

    # Owner отвечает → Управляющий finalize.
    owner_answer = "dev: трогаем только Sonnet, остальные две модели остаются как есть."
    final = tools.finalize_planning_session(
        sid, owner_answer, caller_role=_MD, db_path=db_path
    )
    assert final["статус"] == "ok"
    assert final["status"] == "done"
    created = final["created_tasks"]
    assert len(created) == 1
    new_task_id = created[0]["task_id"]
    assert created[0]["dept"] == "dev"

    # Финальная phase=done, finished_at != None.
    final_session = _db.planning_session_get(db_path, sid)
    assert final_session["phase"] == "done"
    assert final_session["finished_at"] is not None

    # dev-lead (legacy 'тимлид') подхватывает задачу.
    claim = tools.claim_task(new_task_id, assignee="тимлид", db_path=db_path)
    assert claim["статус"] == "ok"
    assert claim["задача"]["assignee"] == "тимлид"

    # Тимлид ведёт через wip → review (safety-net блокирует done).
    upd1 = tools.update_task(new_task_id, status="wip", db_path=db_path)
    assert upd1["задача"]["status"] == "wip"
    upd2 = tools.update_task(new_task_id, status="review", db_path=db_path)
    assert upd2["задача"]["status"] == "review"

    # В памяти Управляющего ищется заметка про этот planning_session.
    search = tools.manager_memory_search(
        query="Sonnet", caller_role=_MD, db_path=db_path
    )
    assert search["статус"] == "ok"
    assert search["всего"] >= 1
    # И самый свежий note виден в recent.
    recent = tools.manager_memory_recent(
        source="planning", caller_role=_MD, db_path=db_path
    )
    assert recent["всего"] >= 1
    assert any(c["path"] == f"planning_session/{sid}" for c in recent["чанки"])

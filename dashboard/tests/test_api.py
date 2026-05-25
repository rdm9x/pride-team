"""REST-тесты Flask-дашборда."""

from __future__ import annotations


def test_index_renders(client) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert b"devboard" in r.data


def test_healthz(client) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.get_json()["status"] == "ok"


def test_list_empty(client) -> None:
    r = client.get("/api/tasks")
    assert r.status_code == 200
    j = r.get_json()
    assert j["задачи"] == []
    assert j["колонки"]["todo"] == []


def test_create_task(client) -> None:
    r = client.post(
        "/api/tasks",
        json={"title": "проверка", "description": "детально"},
    )
    assert r.status_code == 201
    task = r.get_json()["задача"]
    assert task["title"] == "проверка"
    assert task["status"] == "todo"
    # должна появиться в списке
    j = client.get("/api/tasks").get_json()
    assert len(j["задачи"]) == 1
    assert j["колонки"]["todo"][0]["id"] == task["id"]


def test_create_task_validation(client) -> None:
    r = client.post("/api/tasks", json={"title": ""})
    assert r.status_code == 400


def test_get_task_404(client) -> None:
    r = client.get("/api/tasks/deadbeef")
    assert r.status_code == 404


def test_patch_task(client) -> None:
    tid = client.post("/api/tasks", json={"title": "x"}).get_json()["задача"]["id"]
    r = client.patch(f"/api/tasks/{tid}", json={"status": "wip", "assignee": "бэкенд"})
    assert r.status_code == 200
    assert r.get_json()["задача"]["status"] == "wip"


def test_patch_unknown_status(client) -> None:
    tid = client.post("/api/tasks", json={"title": "x"}).get_json()["задача"]["id"]
    r = client.patch(f"/api/tasks/{tid}", json={"status": "мусор"})
    assert r.status_code == 400


def test_comment(client) -> None:
    tid = client.post("/api/tasks", json={"title": "x"}).get_json()["задача"]["id"]
    r = client.post(
        f"/api/tasks/{tid}/comment",
        json={"author": "тимлид", "text": "стартую"},
    )
    assert r.status_code == 201
    t = client.get(f"/api/tasks/{tid}").get_json()["задача"]
    assert len(t["comments"]) == 1


def test_approve_flow(client) -> None:
    # Эмулируем что тимлид (reporter) создал approval-таску для пользователя.
    tid = client.post(
        "/api/tasks",
        json={
            "title": "git push",
            "status": "needs_approval",
            "requires_approval": True,
            "labels": ["approval", "git-push"],
            "assignee": "пользователь",
            "reporter": "тимлид",
        },
    ).get_json()["задача"]["id"]
    r = client.post(f"/api/tasks/{tid}/approve", json={"text": "ok, пушай"})
    assert r.status_code == 200
    t = client.get(f"/api/tasks/{tid}").get_json()["задача"]
    # После approve задача должна вернуться к reporter'у (тимлиду) в todo,
    # чтобы новый прогон тимлида её взял.
    assert t["status"] == "todo"
    assert t["assignee"] == "тимлид"
    authors = [c["author"] for c in t["comments"]]
    assert "пользователь" in authors


def test_approve_returns_to_reporter(client) -> None:
    # Approval-таску создал бэкенд (не пользователь) — после approve должна
    # вернуться бэкенду, не остаться у пользователя.
    tid = client.post(
        "/api/tasks",
        json={
            "title": "x",
            "status": "needs_approval",
            "assignee": "пользователь",
            "reporter": "бэкенд",
        },
    ).get_json()["задача"]["id"]
    r = client.post(f"/api/tasks/{tid}/approve")
    assert r.status_code == 200
    t = client.get(f"/api/tasks/{tid}").get_json()["задача"]
    assert t["status"] == "todo"
    assert t["assignee"] == "бэкенд"


def test_reject_flow(client) -> None:
    tid = client.post(
        "/api/tasks",
        json={"title": "push", "status": "needs_approval"},
    ).get_json()["задача"]["id"]
    r = client.post(f"/api/tasks/{tid}/reject", json={"text": "лучше в dev"})
    assert r.status_code == 200
    t = client.get(f"/api/tasks/{tid}").get_json()["задача"]
    assert t["status"] == "done"


def test_delete(client) -> None:
    tid = client.post("/api/tasks", json={"title": "x"}).get_json()["задача"]["id"]
    r = client.delete(f"/api/tasks/{tid}")
    assert r.status_code == 200
    r = client.get(f"/api/tasks/{tid}")
    assert r.status_code == 404


def test_team_status_stopped(client) -> None:
    r = client.get("/api/team/status")
    assert r.status_code == 200
    assert r.get_json()["status"] == "stopped"


def test_team_start_missing_script(client, tmp_path, monkeypatch) -> None:
    # devboard-work.sh не существует пока — должен вернуть error
    import app as dashboard_app  # type: ignore

    monkeypatch.setattr(
        dashboard_app,
        "_COMMANDS_DIR",
        tmp_path / "no-such-dir",
    )
    r = client.post("/api/team/start")
    assert r.status_code == 409
    assert r.get_json()["reason"] == "missing_script"


def test_user_comment_mirrors_to_chat(client) -> None:
    # Пользователь пишет коммент к задаче → должно появиться сообщение в чате.
    tid = client.post("/api/tasks", json={"title": "Telegram setup"}).get_json()["задача"]["id"]
    r = client.post(
        f"/api/tasks/{tid}/comment",
        json={"author": "пользователь", "text": "TELEGRAM_CHAT_ID=123456789"},
    )
    assert r.status_code == 201
    msgs = client.get("/api/chat").get_json()["messages"]
    assert len(msgs) == 1
    assert msgs[0]["author"] == "пользователь"
    assert "123456789" in msgs[0]["text"]
    assert tid[:6] in msgs[0]["text"]  # ссылка на задачу


def test_bot_comment_does_not_mirror(client) -> None:
    # Комменты от бэкенда/тимлида в чат НЕ зеркалятся.
    tid = client.post("/api/tasks", json={"title": "x"}).get_json()["задача"]["id"]
    client.post(f"/api/tasks/{tid}/comment", json={"author": "бэкенд", "text": "сделано"})
    msgs = client.get("/api/chat").get_json()["messages"]
    assert msgs == []


def test_system_marker_comment_not_mirrored(client) -> None:
    tid = client.post(
        "/api/tasks", json={"title": "x", "status": "needs_approval"}
    ).get_json()["задача"]["id"]
    client.post(f"/api/tasks/{tid}/approve")  # генерит "approved at ..."
    msgs = client.get("/api/chat").get_json()["messages"]
    assert msgs == []  # системные approve-маркеры не зеркалим


def test_dependencies_api(client) -> None:
    a = client.post("/api/tasks", json={"title": "A"}).get_json()["задача"]["id"]
    b = client.post("/api/tasks", json={"title": "B"}).get_json()["задача"]["id"]
    r = client.post(f"/api/tasks/{b}/dependencies", json={"depends_on": a})
    assert r.status_code == 201
    task = client.get(f"/api/tasks/{b}").get_json()["задача"]
    assert len(task["blocked_by"]) == 1
    assert task["blocked_by"][0]["id"] == a
    # удалить связь
    r = client.delete(f"/api/tasks/{b}/dependencies/{a}")
    assert r.status_code == 200
    task = client.get(f"/api/tasks/{b}").get_json()["задача"]
    assert task["blocked_by"] == []


def test_silence_badge_no_sessions(client) -> None:
    r = client.get("/api/team/silence")
    assert r.status_code == 200
    j = r.get_json()
    assert j["silent"] is False


def test_archive_filter_in_list_tasks(client) -> None:
    # Создаём задачу и помечаем как done с completed_at в прошлом > 7 дней
    import sqlite3
    import time as _t

    tid = client.post("/api/tasks", json={"title": "old"}).get_json()["задача"]["id"]
    fresh_tid = client.post("/api/tasks", json={"title": "fresh"}).get_json()["задача"]["id"]
    cutoff = int(_t.time() - 10 * 86400)
    conn = sqlite3.connect(client.application.config["DB_PATH"])
    conn.execute(
        "UPDATE tasks SET status='done', completed_at=? WHERE id=?",
        (cutoff, tid),
    )
    conn.execute(
        "UPDATE tasks SET status='done', completed_at=? WHERE id=?",
        (int(_t.time()), fresh_tid),
    )
    conn.commit()
    conn.close()

    j = client.get("/api/tasks").get_json()
    assert j["архив_count"] == 1
    # Старая не должна быть в основном списке
    titles = [t["title"] for t in j["задачи"]]
    assert "old" not in titles
    assert "fresh" in titles
    # С archived=1 — возвращается
    j2 = client.get("/api/tasks?archived=1").get_json()
    archived_titles = [t["title"] for t in j2["архив"]]
    assert "old" in archived_titles


def test_chat_post_and_list(client) -> None:
    r = client.get("/api/chat")
    assert r.status_code == 200
    assert r.get_json()["messages"] == []
    r = client.post("/api/chat", json={"author": "пользователь", "text": "Привет, тимлид"})
    assert r.status_code == 201
    r = client.post("/api/chat", json={"author": "тимлид", "text": "Слушаю"})
    assert r.status_code == 201
    messages = client.get("/api/chat").get_json()["messages"]
    assert len(messages) == 2
    assert messages[0]["author"] == "пользователь"
    assert messages[1]["author"] == "тимлид"


def test_chat_post_validation(client) -> None:
    r = client.post("/api/chat", json={"author": "hacker", "text": "hi"})
    assert r.status_code == 400
    r = client.post("/api/chat", json={"author": "пользователь", "text": "   "})
    assert r.status_code == 400


def test_inbox_empty(client) -> None:
    r = client.get("/api/inbox")
    assert r.status_code == 200
    j = r.get_json()
    assert j["total"] == 0
    assert j["approvals"] == []
    assert j["reviews"] == []
    assert j["questions"] == []


def test_inbox_groups_correctly(client) -> None:
    # 1. destructive approval с assignee=пользователь
    client.post("/api/tasks", json={
        "title": "git push origin main", "status": "needs_approval",
        "assignee": "пользователь", "reporter": "бэкенд",
        "labels": ["destructive", "git-push"],
    })
    # 2. Approval с assignee=тимлид (после возврата дрегом) — тоже должна
    #    попасть в approvals, потому что физически в столбце needs_approval.
    client.post("/api/tasks", json={
        "title": "A5: ssh-deploy", "status": "needs_approval",
        "assignee": "тимлид", "reporter": "тимлид",
        "labels": ["approval", "ssh"],
    })
    # 3. Приёмка
    client.post("/api/tasks", json={
        "title": "готовый дизайн", "status": "review", "reporter": "тимлид",
    })
    # 4. Вопрос (status=todo)
    client.post("/api/tasks", json={
        "title": "выбери авторизацию", "assignee": "пользователь",
        "labels": ["question"], "reporter": "тимлид",
    })
    # 5. Шум: wip-задача, не для пользователя
    client.post("/api/tasks", json={"title": "wip-shum", "status": "wip", "assignee": "бэкенд"})

    j = client.get("/api/inbox").get_json()
    assert j["total"] == 4
    # Обе needs_approval задачи в approvals, независимо от assignee
    assert len(j["approvals"]) == 2
    approval_titles = {t["title"] for t in j["approvals"]}
    assert approval_titles == {"git push origin main", "A5: ssh-deploy"}
    assert len(j["reviews"]) == 1
    # questions: только status=todo для пользователя (needs_approval поглощён в approvals)
    assert len(j["questions"]) == 1
    assert j["questions"][0]["title"] == "выбери авторизацию"


def test_usage_endpoint_empty(client) -> None:
    r = client.get("/api/usage")
    assert r.status_code == 200
    j = r.get_json()
    assert j["total"]["sessions"] == 0
    assert j["last_5h"]["turns"] == 0
    assert j["models"] == []


def test_usage_endpoint_with_records(client, tmp_path) -> None:
    # Запишем пару сессий напрямую через db.record_claude_session
    import sys
    sys.path.insert(0, str(tmp_path.parent.parent.parent / "mcp_сервер"))
    from devboard_tasks import db as _db  # type: ignore

    # client использует БД из tmp_path/tasks.db через фикстуру
    import app as dashboard_app  # type: ignore

    db_path = dashboard_app.DB_PATH  # тестовая БД
    # Замечание: client.application.config["DB_PATH"] — это правильный путь, не глобальный
    db_path = client.application.config["DB_PATH"]
    import time as _time
    now = int(_time.time())
    _db.record_claude_session(
        db_path,
        started_at=now - 60,
        finished_at=now - 30,
        duration_ms=30000,
        num_turns=5,
        input_tokens=1000,
        output_tokens=500,
        total_cost_usd=0.012,
        model="claude-sonnet",
    )
    _db.record_claude_session(
        db_path,
        started_at=now - 120,
        finished_at=now - 60,
        duration_ms=60000,
        num_turns=8,
        input_tokens=2000,
        output_tokens=1200,
        total_cost_usd=0.034,
        model="claude-opus",
    )
    r = client.get("/api/usage")
    j = r.get_json()
    assert j["total"]["sessions"] == 2
    assert j["total"]["turns"] == 13
    assert j["last_5h"]["sessions"] == 2
    assert j["last_5h"]["cost_usd"] == 0.046
    assert len(j["models"]) == 2


def test_roles_endpoint(client) -> None:
    r = client.get("/api/roles")
    assert r.status_code == 200
    j = r.get_json()
    assert j["статус"] == "ok"
    names = sorted([role["name"] for role in j["роли"]])
    assert names == sorted([
        "dev-lead", "бэкенд", "qa",
        "архитектор", "frontend", "devops", "техписатель",
    ])


def test_columns_grouped_correctly(client) -> None:
    client.post("/api/tasks", json={"title": "a"})
    client.post("/api/tasks", json={"title": "b", "status": "wip"})
    client.post("/api/tasks", json={"title": "c", "status": "needs_approval"})
    client.post("/api/tasks", json={"title": "d", "status": "review"})
    client.post("/api/tasks", json={"title": "e", "status": "done"})
    j = client.get("/api/tasks").get_json()
    assert len(j["колонки"]["todo"]) == 1
    assert len(j["колонки"]["wip"]) == 1
    assert len(j["колонки"]["needs_approval"]) == 1
    assert len(j["колонки"]["review"]) == 1
    assert len(j["колонки"]["done"]) == 1


def test_patch_status_done_ui_not_blocked(client) -> None:
    """PATCH /api/tasks/<id> {"status":"done"} от UI должен работать без блокировки safety-net."""
    tid = client.post("/api/tasks", json={"title": "ui done test"}).get_json()["задача"]["id"]
    r = client.patch(f"/api/tasks/{tid}", json={"status": "done"})
    assert r.status_code == 200
    assert r.get_json()["задача"]["status"] == "done", (
        "PATCH от UI с status=done должен работать — safety-net не блокирует UI"
    )

"""Параллельные тесты атомарности.

Проверяют что fcntl-lock + BEGIN IMMEDIATE действительно сериализуют
параллельных writer'ов: lost-update не происходит, claim_task даёт
exactly-one winner, 8 параллельных writer'ов создают 8 разных задач.
"""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pride_tasks import db, tools


def test_parallel_inserts_8_writers_8_keys(db_path: Path) -> None:
    """8 потоков создают по задаче — в БД ровно 8 разных задач."""

    def worker(i: int) -> str:
        res = tools.create_task(title=f"task-{i}", db_path=db_path)
        assert res["статус"] == "ok"
        return res["задача"]["id"]

    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = [ex.submit(worker, i) for i in range(8)]
        ids = {f.result() for f in as_completed(futures)}

    assert len(ids) == 8, f"должно быть 8 уникальных id, получили {len(ids)}"
    listed = tools.list_tasks(db_path=db_path)
    assert listed["всего"] == 8


def test_claim_race_exactly_one_winner(db_path: Path) -> None:
    """4 потока пытаются claim одну задачу — ровно один побеждает."""

    task = tools.create_task(title="contested", db_path=db_path)
    tid = task["задача"]["id"]

    def claimer(role: str) -> dict:
        return tools.claim_task(tid, role, db_path=db_path)

    roles = ["бэкенд", "qa", "тимлид", "дмитрий"]
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = [ex.submit(claimer, r) for r in roles]
        results = [f.result() for f in as_completed(futures)]

    winners = [r for r in results if r["статус"] == "ok"]
    losers = [r for r in results if r["статус"] == "конфликт"]
    # Все 4 могут победить если SQLite сериализовал так, что один пришёл,
    # потом следующий с тем же assignee... но тут assignee у каждого разный,
    # значит победит ровно один, остальные — конфликт.
    assert len(winners) == 1, f"должен быть ровно 1 winner, получили {len(winners)}"
    assert len(losers) == 3

    fetched = db.get_task(db_path, tid)
    assert fetched["assignee"] == winners[0]["задача"]["assignee"]


def test_no_lost_update_under_concurrent_comments(db_path: Path) -> None:
    """20 параллельных add_comment → 20 строк в task_comments."""

    task = tools.create_task(title="X", db_path=db_path)
    tid = task["задача"]["id"]

    def commenter(i: int) -> None:
        res = tools.add_comment(tid, "тимлид", f"коммент {i}", db_path=db_path)
        assert res["статус"] == "ok"

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(commenter, range(20)))

    fetched = tools.get_task(tid, db_path=db_path)
    assert len(fetched["задача"]["comments"]) == 20


def test_concurrent_update_keeps_consistency(db_path: Path) -> None:
    """8 потоков обновляют title — финальное значение совпадает с одним из них."""

    task = tools.create_task(title="initial", db_path=db_path)
    tid = task["задача"]["id"]
    titles = [f"title-{i}" for i in range(8)]

    def updater(t: str) -> None:
        res = tools.update_task(tid, title=t, db_path=db_path)
        assert res["статус"] == "ok"

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(updater, titles))

    final = tools.get_task(tid, db_path=db_path)
    assert final["задача"]["title"] in titles


def test_wal_mode_active(db_path: Path) -> None:
    """Проверяем что WAL включён (нужен для конкурентных чтений)."""
    conn = sqlite3.connect(db_path)
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()
    assert mode.lower() == "wal"

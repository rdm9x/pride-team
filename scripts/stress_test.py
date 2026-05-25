"""E8.5: Стресс-тест канбана devboard-tasks на 1000 задач + SLA latency.

Создаёт ВРЕМЕННУЮ БД (через tempfile.mkdtemp + DEVBOARD_TASKS_DB), наполняет её
200 родительскими задачами + по 4 подзадачи каждой = 1000 задач, плюс 5000
чат-сообщений. Затем замеряет latency трёх hot-операций по 100 итераций:

  - tools.list_tasks(limit=50)
  - tools.get_task(<random_id>, with_history=True)
  - tools.chat_post + tools.chat_recent(limit=50)

Печатает в stdout сводную таблицу p50/p95/p99 и pass/fail по SLA:
  - list_tasks   p95 < 200 ms
  - get_task     p95 < 100 ms
  - chat_recent  p95 < 100 ms

Запуск:

    python scripts/stress_test.py

Никакие dev-зависимости не нужны — только stdlib (statistics.quantiles).
Пользовательскую БД data/tasks.db скрипт НЕ трогает (DEVBOARD_TASKS_DB
указывает на временный файл, который удаляется в конце).
"""

from __future__ import annotations

import json
import os
import platform
import random
import shutil
import sqlite3
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

# Делаем модуль импортируемым: scripts/ лежит рядом с mcp_server/.
ROOT = Path(__file__).resolve().parents[1]
MCP_DIR = ROOT / "mcp_server"
sys.path.insert(0, str(MCP_DIR))


# === Конфигурация стресс-теста ===

PARENTS = 200
SUBTASKS_PER_PARENT = 4         # 200 * 4 = 800 подзадач => всего 1000 задач
CHAT_MESSAGES_SETUP = 5000      # фоновая нагрузка на chat_messages для реалистичного chat_recent
ITERATIONS = 100                # сколько раз вызвать каждую hot-операцию
LIST_LIMIT = 50
CHAT_LIMIT = 50

SLA_MS = {
    "list_tasks":  200.0,
    "get_task":    100.0,
    "chat_recent": 100.0,
}

ROLES_POOL = ("тимлид", "бэкенд", "qa", "архитектор", "frontend", "devops", "техписатель")
STATUSES_POOL = ("todo", "wip", "needs_approval", "review", "done", "blocked")
PRIORITIES_POOL = ("P0", "P1", "P2", "P3")


# === Замер ===

def measure(label: str, op: Callable[[], object], iterations: int = ITERATIONS) -> dict:
    """Прогоняет op() iterations раз, возвращает p50/p95/p99 в миллисекундах."""
    samples_ms: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        op()
        samples_ms.append((time.perf_counter() - t0) * 1000.0)

    samples_ms.sort()
    # statistics.quantiles с n=100 даёт 99 границ — индексируем напрямую.
    # Для maps p50/p95/p99 используем интерполяцию.
    qs = statistics.quantiles(samples_ms, n=100, method="inclusive")
    p50 = qs[49]   # 50-й перцентиль
    p95 = qs[94]
    p99 = qs[98]
    return {
        "label":  label,
        "n":      iterations,
        "min_ms": samples_ms[0],
        "max_ms": samples_ms[-1],
        "mean_ms": statistics.fmean(samples_ms),
        "p50_ms": p50,
        "p95_ms": p95,
        "p99_ms": p99,
    }


# === Наполнение БД ===

def seed(db_path: Path) -> tuple[list[str], list[str]]:
    """Создаёт 200 parent + 800 sub задач и 5000 chat-сообщений.

    Возвращает (parent_ids, all_task_ids).
    """
    from devboard_tasks import db  # импорт после sys.path-патча

    db.init_db(db_path)

    rng = random.Random(42)
    parent_ids: list[str] = []
    all_ids: list[str] = []

    t0 = time.perf_counter()
    for i in range(PARENTS):
        parent = db.insert_task(
            db_path,
            title=f"Parent task #{i:04d} — большой эпик с длинным заголовком чтобы данные были не идеально-короткие",
            description=(
                "Это родительская задача из стресс-теста. "
                "Описание умышленно длиннее одной строки, чтобы IO read был реалистичным. "
                "lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 3
            ),
            assignee=rng.choice(ROLES_POOL),
            reporter="тимлид",
            priority=rng.choice(PRIORITIES_POOL),
            status=rng.choice(STATUSES_POOL),
            labels=rng.sample(
                ["perf", "qa", "backend", "frontend", "infra", "ui", "tech-debt", "ci"],
                k=rng.randint(0, 3),
            ),
        )
        parent_ids.append(parent["id"])
        all_ids.append(parent["id"])

    for parent_id in parent_ids:
        for j in range(SUBTASKS_PER_PARENT):
            sub = db.insert_task(
                db_path,
                title=f"Sub #{j} of {parent_id[:6]} — конкретный подшаг с осмысленным заголовком",
                description="Подзадача стресс-теста. Короче родителя, но не пустая.",
                assignee=rng.choice(ROLES_POOL),
                reporter="тимлид",
                priority=rng.choice(PRIORITIES_POOL),
                parent_id=parent_id,
                status=rng.choice(STATUSES_POOL),
                labels=rng.sample(["perf", "qa", "ui", "backend"], k=rng.randint(0, 2)),
            )
            all_ids.append(sub["id"])

    insert_elapsed = time.perf_counter() - t0
    print(f"[seed] tasks insert: {len(all_ids)} штук за {insert_elapsed:.2f}s "
          f"({len(all_ids)/insert_elapsed:.0f} task/s)")

    # Чат-сообщения — батчами, чтобы не платить fcntl-lock 5000 раз.
    t1 = time.perf_counter()
    now0 = int(time.time()) - CHAT_MESSAGES_SETUP
    with db.write_lock(db_path):
        conn = sqlite3.connect(db_path, timeout=10.0, isolation_level=None)
        try:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("BEGIN IMMEDIATE")
            for k in range(CHAT_MESSAGES_SETUP):
                conn.execute(
                    "INSERT INTO chat_messages (author, text, created_at) VALUES (?, ?, ?)",
                    (
                        rng.choice(("пользователь", "тимлид", "бэкенд", "qa", "system")),
                        f"chat msg #{k:05d} — какой-то осмысленный текст про задачу или ревью",
                        now0 + k,
                    ),
                )
            conn.execute("COMMIT")
        finally:
            conn.close()
    print(f"[seed] chat insert: {CHAT_MESSAGES_SETUP} msg за {time.perf_counter()-t1:.2f}s")

    return parent_ids, all_ids


# === Хелперы ===

def fmt_ms(v: float) -> str:
    return f"{v:7.2f}"

def banner(text: str) -> None:
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def detect_env() -> dict:
    cpu = platform.processor() or platform.machine()
    try:
        import subprocess
        if sys.platform == "darwin":
            cpu = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip()
    except Exception:
        pass
    try:
        if sys.platform == "darwin":
            import subprocess
            mem_bytes = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip())
            mem = f"{mem_bytes / 1024**3:.0f} GB"
        else:
            mem = "n/a"
    except Exception:
        mem = "n/a"
    return {
        "python": sys.version.split()[0],
        "sqlite_lib": sqlite3.sqlite_version,
        "sqlite_module": sqlite3.version,
        "os": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "cpu": cpu,
        "ram": mem,
    }


# === Главный сценарий ===

def main() -> int:
    env = detect_env()
    banner("E8.5 stress test — devboard-tasks (1000 задач, 5000 chat-сообщений)")
    print(f"Python:       {env['python']}")
    print(f"SQLite:       {env['sqlite_lib']} (модуль {env['sqlite_module']})")
    print(f"OS:           {env['os']}")
    print(f"CPU:          {env['cpu']}")
    print(f"RAM:          {env['ram']}")

    # ВРЕМЕННАЯ БД — не трогаем data/tasks.db пользователя.
    tmpdir = Path(tempfile.mkdtemp(prefix="pride_stress_"))
    db_path = tmpdir / "tasks.db"
    # DEVBOARD_TASKS_DB не обязателен (мы явно передаём db_path), но выставим — чтобы
    # любая невидимая обёртка тоже знала, что не надо лезть в data/tasks.db.
    os.environ["DEVBOARD_TASKS_DB"] = str(db_path)
    print(f"Temp DB:      {db_path}")

    try:
        from devboard_tasks import tools  # тулзы канбана

        parent_ids, all_ids = seed(db_path)
        # WAL-checkpoint, чтобы первые читатели не получали страницы из WAL.
        conn = sqlite3.connect(db_path, timeout=10.0)
        conn.execute("PRAGMA wal_checkpoint(FULL);")
        conn.close()
        size_mb = db_path.stat().st_size / 1024**2
        print(f"DB size:      {size_mb:.2f} MB ({len(all_ids)} tasks, {CHAT_MESSAGES_SETUP} chat msgs)")

        # Прогрев — стартовая JIT/кеш-warmup чтобы первая итерация не была outlier.
        for _ in range(3):
            tools.list_tasks(limit=LIST_LIMIT, db_path=db_path)
            tools.get_task(random.choice(all_ids), db_path=db_path)
            tools.chat_recent(limit=CHAT_LIMIT, db_path=db_path)

        rng = random.Random(7)

        banner("Бенчмарки (N=100 итераций каждой операции)")

        # 1) list_tasks
        res_list = measure(
            "list_tasks(limit=50)",
            lambda: tools.list_tasks(limit=LIST_LIMIT, db_path=db_path),
        )

        # 2) get_task — случайный ID
        def _op_get():
            tid = rng.choice(all_ids)
            tools.get_task(tid, db_path=db_path)
        res_get = measure("get_task(random, with_history=True)", _op_get)

        # 3) chat_post + chat_recent — операция как единое целое (E8.5 пункт 3)
        post_counter = {"n": 0}
        def _op_chat():
            post_counter["n"] += 1
            tools.chat_post("qa", f"stress probe #{post_counter['n']}", db_path=db_path)
            tools.chat_recent(limit=CHAT_LIMIT, db_path=db_path)
        res_chat_combined = measure("chat_post + chat_recent(limit=50)", _op_chat)

        # 3b) Отдельно ещё раз чистый chat_recent — это против чего сравниваем SLA.
        res_chat_read = measure(
            "chat_recent(limit=50)",
            lambda: tools.chat_recent(limit=CHAT_LIMIT, db_path=db_path),
        )

        results = [
            ("list_tasks",   res_list,          SLA_MS["list_tasks"]),
            ("get_task",     res_get,           SLA_MS["get_task"]),
            ("chat_recent",  res_chat_read,     SLA_MS["chat_recent"]),
        ]

        # Печать
        print(f"\n{'endpoint':<25}{'p50 ms':>10}{'p95 ms':>10}{'p99 ms':>10}"
              f"{'mean ms':>10}{'max ms':>10}  {'SLA':>8}  {'verdict':>8}")
        print("-" * 100)
        all_pass = True
        for name, r, sla in results:
            verdict = "PASS" if r["p95_ms"] < sla else "FAIL"
            if verdict == "FAIL":
                all_pass = False
            print(f"{name:<25}{fmt_ms(r['p50_ms']):>10}{fmt_ms(r['p95_ms']):>10}"
                  f"{fmt_ms(r['p99_ms']):>10}{fmt_ms(r['mean_ms']):>10}"
                  f"{fmt_ms(r['max_ms']):>10}  {sla:>6.0f}ms  {verdict:>8}")

        # Дополнительные строки — для контекста, без SLA.
        print()
        print("Дополнительно (без SLA, для контекста):")
        r = res_chat_combined
        print(f"  chat_post+chat_recent       p50={r['p50_ms']:.2f}ms "
              f"p95={r['p95_ms']:.2f}ms p99={r['p99_ms']:.2f}ms (вкл. write_lock)")

        banner("Итог")
        print("ВСЕ SLA ВЫПОЛНЕНЫ" if all_pass else "ЕСТЬ FAIL — см. таблицу выше")

        # Дамп в JSON — для последующей загрузки в perf-baseline.md
        report = {
            "env":   env,
            "load": {
                "tasks": len(all_ids),
                "chat_messages": CHAT_MESSAGES_SETUP,
                "db_size_mb": round(size_mb, 2),
            },
            "results": [
                {"endpoint": name, "sla_ms": sla, "verdict": ("PASS" if r["p95_ms"] < sla else "FAIL"), **r}
                for name, r, sla in results
            ],
            "extras": {"chat_post_plus_recent": res_chat_combined},
        }
        out_json = ROOT / "docs" / "qa" / "perf-baseline.json"
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON-отчёт: {out_json}")

        return 0 if all_pass else 1
    finally:
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())

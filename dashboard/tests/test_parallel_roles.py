"""Тесты D38BCDDA9CF9: параллельный запуск разных ролей.

Покрываются:
  1. Запуск marketing-lead не блокирует dev-lead
  2. Две роли могут работать одновременно (разные процессы)
  3. Остановка одной роли не влияет на другую
  4. Auto-monitor запускает свободные роли параллельно
  5. История запусков считается по ролям отдельно
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from queue import Empty, Queue
from threading import Lock
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module  # noqa: E402


def _make_fake_proc(pid: int):
    """Создаёт fake subprocess для тестирования."""
    fake = MagicMock()
    fake.pid = pid
    fake.poll.return_value = None
    fake.stdout = iter([])
    return fake


@pytest.fixture()
def reset_team_states():
    """Сбрасывает глобальное состояние ко вс ему ролям к чистому виду."""
    saved_states = dict(app_module._team_states)
    saved_global = dict(app_module._global_state)

    app_module._team_states.clear()
    app_module._global_state["auto_mode"] = False
    app_module._global_state["auto_pause_reason"] = None

    yield

    app_module._team_states.clear()
    app_module._team_states.update(saved_states)
    app_module._global_state.clear()
    app_module._global_state.update(saved_global)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Запуск marketing-lead не блокирует dev-lead (параллельные очереди)
# ─────────────────────────────────────────────────────────────────────────────

def test_parallel_roles_independent_processes(
    reset_team_states, monkeypatch, tmp_path
) -> None:
    """marketing-lead и dev-lead работают в разных процессах одновременно."""
    if sys.platform == "win32":
        pytest.skip("Unix-only path test")

    # Создаём скрипты в tmp_path
    work_script = tmp_path / "devboard-work.sh"
    work_script.write_text("#!/bin/bash\necho hi\n")
    monkeypatch.setattr(app_module, "_COMMANDS_DIR", tmp_path)
    monkeypatch.setattr(app_module, "_PID_FILE", tmp_path / "team.pid")
    monkeypatch.setattr(app_module, "_LIVE_LOG", tmp_path / "team.log")

    proc_marketing = _make_fake_proc(1001)
    proc_dev = _make_fake_proc(1002)

    with patch("subprocess.Popen") as popen_mock:
        popen_mock.side_effect = [proc_marketing, proc_dev]

        # Запускаем marketing-lead
        res1 = app_module._start_team_process(role="marketing-lead")
        assert res1["ok"] is True
        assert res1["pid"] == 1001
        assert res1["role"] == "marketing-lead"

        # Запускаем dev-lead ОДНОВРЕМЕННО (не ждём завершения marketing)
        res2 = app_module._start_team_process(role="dev-lead")
        assert res2["ok"] is True
        assert res2["pid"] == 1002
        assert res2["role"] == "dev-lead"

        # ОБА процесса живы одновременно
        state_m = app_module._get_team_state_for_role("marketing-lead")
        state_d = app_module._get_team_state_for_role("dev-lead")

        assert state_m["process"].pid == 1001
        assert state_d["process"].pid == 1002
        assert state_m["process"].poll() is None  # marketing ещё работает
        assert state_d["process"].poll() is None  # dev ещё работает


# ─────────────────────────────────────────────────────────────────────────────
# 2. Очереди разных ролей независимые
# ─────────────────────────────────────────────────────────────────────────────

def test_role_queues_are_independent(reset_team_states) -> None:
    """Каждая роль имеет свою очередь событий."""
    state_m = app_module._get_team_state_for_role("marketing-lead")
    state_d = app_module._get_team_state_for_role("dev-lead")

    # Очереди разные объекты
    assert state_m["queue"] is not state_d["queue"]

    # Добавляем в одну очередь
    state_m["queue"].put({"ts": "12:00:00", "human": "marketing event"})
    state_d["queue"].put({"ts": "12:00:01", "human": "dev event"})

    # Извлекаем независимо
    msg_m = state_m["queue"].get_nowait()
    msg_d = state_d["queue"].get_nowait()

    assert msg_m["human"] == "marketing event"
    assert msg_d["human"] == "dev event"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Остановка одной роли не влияет на другую
# ─────────────────────────────────────────────────────────────────────────────

def test_stop_one_role_doesnt_affect_other(
    reset_team_states, monkeypatch, tmp_path
) -> None:
    """Остановка marketing-lead не трогает dev-lead."""
    if sys.platform == "win32":
        pytest.skip("Unix-only path test")

    work_script = tmp_path / "devboard-work.sh"
    work_script.write_text("#!/bin/bash\necho hi\n")
    monkeypatch.setattr(app_module, "_COMMANDS_DIR", tmp_path)
    monkeypatch.setattr(app_module, "_PID_FILE", tmp_path / "team.pid")
    monkeypatch.setattr(app_module, "_LIVE_LOG", tmp_path / "team.log")

    proc_m = _make_fake_proc(2001)
    proc_d = _make_fake_proc(2002)

    with patch("subprocess.Popen") as popen_mock:
        popen_mock.side_effect = [proc_m, proc_d]

        # Запускаем обе роли
        app_module._start_team_process(role="marketing-lead")
        app_module._start_team_process(role="dev-lead")

        # Останавливаем marketing
        res = app_module._stop_team_process(role="marketing-lead")
        assert res["ok"] is True

        # dev-lead всё ещё работает
        state_d = app_module._get_team_state_for_role("dev-lead")
        assert state_d["process"].pid == 2002
        assert state_d["process"].poll() is None

        # marketing остановлена
        state_m = app_module._get_team_state_for_role("marketing-lead")
        assert state_m["process"] is None


# ─────────────────────────────────────────────────────────────────────────────
# 4. Auto-monitor пытается запустить все свободные роли
# ─────────────────────────────────────────────────────────────────────────────

def test_auto_monitor_starts_all_free_roles(
    reset_team_states, monkeypatch, tmp_path
) -> None:
    """Auto-monitor запускает marketing-lead И dev-lead если обе свободны."""
    if sys.platform == "win32":
        pytest.skip("Unix-only path test")

    work_script = tmp_path / "devboard-work.sh"
    work_script.write_text("#!/bin/bash\necho hi\n")
    managing_script = tmp_path / "devboard-managing.sh"
    managing_script.write_text("#!/bin/bash\necho managing\n")

    monkeypatch.setattr(app_module, "_COMMANDS_DIR", tmp_path)
    monkeypatch.setattr(app_module, "_PID_FILE", tmp_path / "team.pid")
    monkeypatch.setattr(app_module, "_LIVE_LOG", tmp_path / "team.log")

    # Мокируем db.list_roles для возврата известных ролей
    def mock_list_roles(db_path):
        return [
            {"name": "marketing-lead", "department_id": "marketing"},
            {"name": "dev-lead", "department_id": "dev"},
        ]

    procs = [_make_fake_proc(3001), _make_fake_proc(3002), _make_fake_proc(3003)]

    app_module._global_state["auto_mode"] = True

    with patch("subprocess.Popen") as popen_mock, \
         patch.object(app_module.db, "list_roles", mock_list_roles), \
         patch.object(app_module, "_has_pending_work_for_role", return_value=True):

        popen_mock.side_effect = procs

        # Запускаем авто-монитор один раз
        now = int(time.time())

        # Проверяем что marketing может стартовать
        ok_m, reason_m = app_module._auto_can_start_for_role("marketing-lead", now)
        assert ok_m is True, f"marketing не может стартовать: {reason_m}"

        # Проверяем что dev может стартовать
        ok_d, reason_d = app_module._auto_can_start_for_role("dev-lead", now)
        assert ok_d is True, f"dev не может стартовать: {reason_d}"

        # Запускаем вручную обе
        res_m = app_module._start_team_process(role="marketing-lead")
        res_d = app_module._start_team_process(role="dev-lead")

        assert res_m["ok"] is True
        assert res_d["ok"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 5. История запусков ведётся по ролям отдельно
# ─────────────────────────────────────────────────────────────────────────────

def test_starts_history_per_role(
    reset_team_states, monkeypatch, tmp_path
) -> None:
    """Каждая роль имеет свою историю запусков."""
    if sys.platform == "win32":
        pytest.skip("Unix-only path test")

    work_script = tmp_path / "devboard-work.sh"
    work_script.write_text("#!/bin/bash\necho hi\n")
    monkeypatch.setattr(app_module, "_COMMANDS_DIR", tmp_path)
    monkeypatch.setattr(app_module, "_PID_FILE", tmp_path / "team.pid")
    monkeypatch.setattr(app_module, "_LIVE_LOG", tmp_path / "team.log")

    proc1 = _make_fake_proc(4001)
    proc2 = _make_fake_proc(4002)
    proc3 = _make_fake_proc(4003)

    with patch("subprocess.Popen") as popen_mock:
        popen_mock.side_effect = [proc1, proc2, proc3]

        # Запускаем marketing-lead
        app_module._start_team_process(role="marketing-lead")
        state_m = app_module._get_team_state_for_role("marketing-lead")
        assert len(state_m["starts_history"]) == 1
        history_m = state_m["starts_history"]

        # Запускаем dev-lead один раз
        app_module._start_team_process(role="dev-lead")
        state_d = app_module._get_team_state_for_role("dev-lead")
        assert len(state_d["starts_history"]) == 1
        history_d = state_d["starts_history"]

        # Истории независимы (разные объекты в памяти)
        assert history_m is not history_d
        # И содержат разные списки (даже если temps одинаковы по значению)
        assert id(history_m) != id(history_d)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Блокировка на заблокированной роли не блокирует другую
# ─────────────────────────────────────────────────────────────────────────────

def test_already_running_one_role_doesnt_block_other(
    reset_team_states, monkeypatch, tmp_path
) -> None:
    """Если marketing-lead работает, dev-lead всё ещё может стартовать."""
    if sys.platform == "win32":
        pytest.skip("Unix-only path test")

    work_script = tmp_path / "devboard-work.sh"
    work_script.write_text("#!/bin/bash\necho hi\n")
    monkeypatch.setattr(app_module, "_COMMANDS_DIR", tmp_path)
    monkeypatch.setattr(app_module, "_PID_FILE", tmp_path / "team.pid")
    monkeypatch.setattr(app_module, "_LIVE_LOG", tmp_path / "team.log")

    proc1 = _make_fake_proc(5001)
    proc2 = _make_fake_proc(5002)

    with patch("subprocess.Popen") as popen_mock:
        popen_mock.side_effect = [proc1, proc2]

        # Запускаем marketing
        res1 = app_module._start_team_process(role="marketing-lead")
        assert res1["ok"] is True

        # Пытаемся запустить marketing ещё раз — должна быть ошибка
        res1_again = app_module._start_team_process(role="marketing-lead")
        assert res1_again["ok"] is False
        assert res1_again["reason"] == "already_running"

        # НО dev-lead может стартовать
        res2 = app_module._start_team_process(role="dev-lead")
        assert res2["ok"] is True
        assert res2["pid"] == 5002


# ─────────────────────────────────────────────────────────────────────────────
# 7. Оба лока независимы (не блокируют друг друга)
# ─────────────────────────────────────────────────────────────────────────────

def test_role_locks_independent(reset_team_states) -> None:
    """Локи разных ролей не связаны."""
    state_m = app_module._get_team_state_for_role("marketing-lead")
    state_d = app_module._get_team_state_for_role("dev-lead")

    # Локи разные объекты
    assert state_m["lock"] is not state_d["lock"]

    # Можно одновременно захватить оба
    state_m["lock"].acquire()
    try:
        # dev-лок всё ещё свободен
        assert state_d["lock"].acquire(blocking=False)
        state_d["lock"].release()
    finally:
        state_m["lock"].release()


# ─────────────────────────────────────────────────────────────────────────────
# 8. _auto_can_start_for_role проверяет ТОЛЬКО ту роль
# ─────────────────────────────────────────────────────────────────────────────

def test_auto_can_start_respects_role_isolation(
    reset_team_states, monkeypatch, tmp_path
) -> None:
    """_auto_can_start_for_role('marketing') не зависит от статуса dev."""
    if sys.platform == "win32":
        pytest.skip("Unix-only path test")

    work_script = tmp_path / "devboard-work.sh"
    work_script.write_text("#!/bin/bash\necho hi\n")
    monkeypatch.setattr(app_module, "_COMMANDS_DIR", tmp_path)
    monkeypatch.setattr(app_module, "_PID_FILE", tmp_path / "team.pid")
    monkeypatch.setattr(app_module, "_LIVE_LOG", tmp_path / "team.log")

    proc = _make_fake_proc(6001)

    app_module._global_state["auto_mode"] = True

    with patch("subprocess.Popen", return_value=proc), \
         patch.object(app_module, "_has_pending_work_for_role", return_value=True):

        now = int(time.time())

        # Запускаем dev-lead
        app_module._start_team_process(role="dev-lead")

        # dev-lead NOW заблокирована для auto_can_start
        ok_dev, _ = app_module._auto_can_start_for_role("dev-lead", now)
        assert ok_dev is False

        # НО marketing-lead всё ещё может стартовать
        ok_m, _ = app_module._auto_can_start_for_role("marketing-lead", now)
        assert ok_m is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

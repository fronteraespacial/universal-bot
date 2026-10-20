"""Los botones funcionan en el runtime de verdad (run_once con resultados diferidos del puente)."""

import json
import time

from universal_bot.code_mode.clock import FakeClock
from universal_bot.code_mode.config import CodeModeConfig
from universal_bot.code_mode.heartbeat import HeartbeatThread
from universal_bot.labcode_runtime import run_once
from tests.test_proposal_ops import (
    CATEGORY, CHANNEL, GUILD, JULIAN, NEW_CHANNEL, NEW_THREAD, PROJECTS, SLUG, T0,
    FakeLabs, bodies, click, completing, make_spool, write_job,
)


def _config(projects=PROJECTS):
    return CodeModeConfig(
        allowed_channels=(CHANNEL, NEW_CHANNEL, PROJECTS),
        admin_category_id=CATEGORY,
        projects_channel_id=projects,
        role_map=((str(JULIAN), ("@dev", "@admin")),),
    )


def _drive(tmp_path, opt, sleeper_for=completing):
    spool = make_spool(tmp_path / "spool")
    db = tmp_path / "mode.sqlite"
    clock = FakeClock(T0)
    sleeper = sleeper_for(spool)
    write_job(spool)
    run_once(spool, db_path=db, clock=clock, lab_runner=FakeLabs(), config=_config(), sleeper=sleeper)
    click(spool, opt)
    run_once(spool, db_path=db, clock=clock, lab_runner=FakeLabs(), config=_config(), sleeper=sleeper)
    return spool, db


def _sessions(db):
    import sqlite3

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute("SELECT * FROM code_mode_sessions WHERE status = 'ACTIVE'")]


def _pins(ops):
    return [(op["channel_id"], op["message_id"]) for op in ops if op["op"] == "pin"]


def test_create_channel_in_the_runtime_moves_the_session_and_pins(tmp_path):
    spool, db = _drive(tmp_path, "create_channel")
    ops = bodies(spool)
    created = [op for op in ops if op["op"] == "create_channel"]
    assert len(created) == 1 and created[0]["parent_id"] == CATEGORY and created[0]["name"] == SLUG
    active = _sessions(db)
    assert [(s["channel_id"], s["thread_id"]) for s in active] == [(NEW_CHANNEL, None)]
    assert _pins(ops) == [(NEW_CHANNEL, 900)]
    assert active[0]["pinned_message_id"] == 900
    assert {op["channel_id"] for op in ops if op["op"] == "thread"} == {NEW_CHANNEL}


def test_create_thread_in_the_runtime_moves_the_session_and_pins(tmp_path):
    spool, db = _drive(tmp_path, "create_thread")
    ops = bodies(spool)
    opened = [op for op in ops if op["op"] == "thread" and op.get("name") == SLUG]
    assert len(opened) == 1 and opened[0]["channel_id"] == PROJECTS
    active = _sessions(db)
    assert [(s["channel_id"], s["thread_id"]) for s in active] == [(PROJECTS, NEW_THREAD)]
    assert _pins(ops) == [(NEW_THREAD, 900)]


def test_here_in_the_runtime_pins_the_real_message(tmp_path):
    spool, db = _drive(tmp_path, "here_1h")
    ops = bodies(spool)
    assert _pins(ops) == [(CHANNEL, 900)]
    assert [(s["channel_id"], s["pinned_message_id"]) for s in _sessions(db)] == [(CHANNEL, 900)]


def _silent(spool):
    def sleeper(_seconds):
        return None

    return sleeper


def test_bridge_that_never_answers_does_not_crash_the_runtime(tmp_path):
    spool, db = _drive(tmp_path, "create_channel", sleeper_for=_silent)
    state = json.loads((spool / "inbox" / "lc_555" / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "error"
    assert state["error"] == "bridge_timeout"
    assert _sessions(db) == []
    again = run_once(spool, db_path=db, clock=FakeClock(T0), lab_runner=FakeLabs(), config=_config(), sleeper=_silent(spool))
    assert again["processed"] == 0
    assert len([op for op in bodies(spool) if op["op"] == "create_channel"]) == 1


def test_heartbeat_thread_keeps_the_file_fresh_during_long_work(tmp_path):
    spool = make_spool(tmp_path / "spool")
    beat = HeartbeatThread(spool, interval_s=0.05)
    beat.start()
    try:
        path = spool / "runtime.heartbeat"
        deadline = time.monotonic() + 3
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        first = path.stat().st_mtime_ns
        time.sleep(0.3)
        assert path.stat().st_mtime_ns > first
    finally:
        beat.stop()
    assert not beat.is_alive()

"""Modo de proceso fijo (warm) para codex/opencode/agy/grok, con fakes de proceso real."""

import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path

import pytest

from universal_bot.code_mode.warm import (
    CAPABILITIES,
    TurnResult,
    WarmError,
    WarmPool,
    make_session,
    warm_argv,
)

FAKES = Path(__file__).resolve().parent / "fakes"
CLIS = ("codex", "opencode", "agy", "grok")
MODELS = {"codex": "gpt-6-luna", "opencode": "opencode/nemotron-3.5-lightning-free", "agy": "gemini-3.8-flash-low", "grok": "grok-4.7"}
STEER = "CAMBIO DE INSTRUCCIÓN: cortá acá y respondé STEERED"


def fake_command(cli):
    return [sys.executable, str(FAKES / f"warm_{cli}.py")]


def session_for(cli, tmp_path, env=None):
    return make_session(cli, MODELS[cli], cwd=tmp_path, command=fake_command(cli), env=env)


def test_argv_per_cli():
    assert warm_argv("codex", "gpt-6-luna", "low") == ["codex", "app-server"]
    assert warm_argv("grok", "grok-4.7", "low") == ["grok", "agent", "-m", "grok-4.7", "--effort", "low", "--always-approve", "stdio"]
    assert warm_argv("agy", "gemini-3.8-flash-low", "low") == [
        "agy", "--input-format", "stream-json", "--output-format", "stream-json",
        "--model", "gemini-3.8-flash-low", "--dangerously-skip-permissions",
    ]
    assert warm_argv("opencode", "opencode/x", "low", port=4599) == ["opencode", "serve", "--hostname", "127.0.0.1", "--port", "4599"]
    with pytest.raises(WarmError):
        warm_argv("otro", "m", "low")


def test_declared_capabilities():
    assert CAPABILITIES["codex"].supports_live_steer is True
    assert CAPABILITIES["opencode"].supports_live_steer is True
    assert CAPABILITIES["grok"].supports_live_steer is False
    assert CAPABILITIES["agy"].supports_live_steer is False
    assert CAPABILITIES["codex"].steer_strategy == "live"
    assert CAPABILITIES["opencode"].steer_strategy == "live"
    assert CAPABILITIES["grok"].steer_strategy == "cancel_reprompt"
    assert CAPABILITIES["agy"].steer_strategy == "interrupt_resume"


@pytest.mark.parametrize("cli", CLIS)
def test_two_prompts_reuse_the_same_process(cli, tmp_path):
    session = session_for(cli, tmp_path)
    session.start()
    try:
        pid = session.pid
        first = session.prompt("Respondé solo OK", timeout_s=10)
        second = session.prompt("Respondé solo OK", timeout_s=10)
        assert isinstance(first, TurnResult)
        assert (first.ok, first.status, first.text.strip()) == (True, "completed", "OK")
        assert second.text.strip() == "OK"
        assert first.first_token_ms is not None and first.duration_ms >= first.first_token_ms
        assert session.pid == pid
        assert session.capabilities is CAPABILITIES[cli]
    finally:
        session.close()
    assert session.alive() is False


def _prompt_in_thread(session, text, timeout_s=15):
    box = {}
    thread = threading.Thread(target=lambda: box.setdefault("result", session.prompt(text, timeout_s=timeout_s)))
    thread.start()
    deadline = time.monotonic() + 5
    while session.streamed_chars == 0 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert session.streamed_chars > 0
    return thread, box


@pytest.mark.parametrize("cli", CLIS)
def test_steer_mid_turn_ends_steered(cli, tmp_path):
    session = session_for(cli, tmp_path)
    session.start()
    try:
        thread, box = _prompt_in_thread(session, "LONG contá hasta 400")
        outcome = session.steer(STEER)
        thread.join(15)
        result = box["result"]
        assert outcome == CAPABILITIES[cli].steer_strategy
        assert result.ok is True
        assert "STEERED" in result.text
        assert result.steered == CAPABILITIES[cli].steer_strategy
    finally:
        session.close()


@pytest.mark.parametrize("cli", CLIS)
def test_cancel_mid_turn(cli, tmp_path):
    session = session_for(cli, tmp_path)
    session.start()
    try:
        thread, box = _prompt_in_thread(session, "LONG contá hasta 400")
        session.cancel()
        thread.join(15)
        assert box["result"].ok is False
        assert box["result"].status == "cancelled"
        assert session.prompt("Respondé solo OK", timeout_s=10).text.strip() == "OK"
    finally:
        session.close()


@pytest.mark.parametrize("cli", CLIS)
def test_turn_timeout_cancels_and_reports(cli, tmp_path):
    session = session_for(cli, tmp_path)
    session.start()
    try:
        result = session.prompt("LONG contá hasta 400", timeout_s=0.4)
        assert (result.ok, result.status) == (False, "timeout")
    finally:
        session.close()


def test_steer_without_turn_is_rejected(tmp_path):
    session = session_for("codex", tmp_path)
    session.start()
    try:
        assert session.steer(STEER) == "no_turn"
    finally:
        session.close()


def test_agy_dying_on_sigint_restarts_once_and_resumes_with_the_new_instruction(tmp_path):
    session = session_for("agy", tmp_path, env={"FAKE_AGY_DIE_ON_SIGINT": "1"})
    session.start()
    try:
        first_pid = session.pid
        thread, box = _prompt_in_thread(session, "LONG contá hasta 400")
        assert session.steer(STEER) == "interrupt_resume"
        thread.join(15)
        assert "STEERED" in box["result"].text
        assert session.restarts == 1
        assert session.pid != first_pid
    finally:
        session.close()


def test_opencode_password_never_leaks(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    session = session_for("opencode", tmp_path)
    session.start()
    try:
        secret = session._password
        assert secret and len(secret) >= 24
        assert session.prompt("Respondé solo OK", timeout_s=10).text.strip() == "OK"
        assert secret not in repr(session)
        assert secret not in caplog.text
        assert secret not in " ".join(session.argv)
    finally:
        session.close()


def test_opencode_falls_back_to_the_printed_password_without_logging_it(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    session = session_for("opencode", tmp_path, env={"FAKE_IGNORE_ENV_PASSWORD": "1"})
    session.start()
    try:
        assert session.prompt("Respondé solo OK", timeout_s=10).text.strip() == "OK"
        assert "fake-printed-password" not in caplog.text
        assert "fake-printed-password" not in repr(session)
    finally:
        session.close()


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _pool(tmp_path, clock=None, env=None, idle=60.0):
    def factory(cli, model):
        return make_session(cli, model, cwd=tmp_path, command=fake_command(cli), env=env)

    return WarmPool(factory, idle_timeout_s=idle, clock=clock or Clock())


def test_pool_keeps_one_hot_process_per_cli_and_model(tmp_path):
    pool = _pool(tmp_path)
    try:
        a = pool.session("grok", "grok-4.7")
        b = pool.session("grok", "grok-4.7")
        c = pool.session("grok", "grok-4.7-fast")
        assert a is b and a is not c
        assert a.pid != c.pid
    finally:
        pool.close()


def test_pool_closes_idle_sessions(tmp_path):
    clock = Clock()
    pool = _pool(tmp_path, clock=clock, idle=30)
    try:
        session = pool.session("codex", "gpt-6-luna")
        pool.run("codex", "gpt-6-luna", "Respondé solo OK", timeout_s=10)
        clock.now = 29
        assert pool.reap_idle() == []
        clock.now = 61
        assert pool.reap_idle() == [("codex", "gpt-6-luna")]
        assert session.alive() is False
    finally:
        pool.close()


def test_pool_restarts_a_dead_process_once_and_then_reports(tmp_path):
    pool = _pool(tmp_path)
    try:
        first = pool.session("grok", "grok-4.7")
        os.kill(first.pid, signal.SIGKILL)
        first.wait_dead(5)
        second = pool.session("grok", "grok-4.7")
        assert second.alive() and second.pid != first.pid
        os.kill(second.pid, signal.SIGKILL)
        second.wait_dead(5)
        with pytest.raises(WarmError) as raised:
            pool.session("grok", "grok-4.7")
        assert raised.value.code == "restart_exhausted"
        assert [e["event"] for e in pool.events] == ["restart", "restart_exhausted"]
    finally:
        pool.close()


def test_pool_falls_back_to_one_shot_when_warm_fails(tmp_path):
    calls = []

    def oneshot(cli, model, text):
        calls.append((cli, model, text))
        return "OK one-shot"

    pool = _pool(tmp_path, env={"FAKE_DIE_ON_TURN": "1"})
    try:
        result = pool.run("codex", "gpt-6-luna", "Respondé solo OK", timeout_s=5, oneshot=oneshot)
        assert result.mode == "oneshot"
        assert result.ok is True and result.text == "OK one-shot"
        assert calls == [("codex", "gpt-6-luna", "Respondé solo OK")]
        assert pool.events and pool.events[-1]["event"] == "fallback_oneshot"
    finally:
        pool.close()


def test_pool_warm_result_is_marked_warm(tmp_path):
    pool = _pool(tmp_path)
    try:
        result = pool.run("agy", "gemini-3.8-flash-low", "Respondé solo OK", timeout_s=10)
        assert result.mode == "warm" and result.text.strip() == "OK"
    finally:
        pool.close()

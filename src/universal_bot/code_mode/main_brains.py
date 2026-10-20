"""Cerebros del MAIN.

- SidecarSession: cursor-sdk vía el sidecar (adapters/cursor_sdk). Un run por turno; el steer en vivo va por
  `steer_file` y el corte por `cancel_file`. La historia de la charla viaja en el prompt.
- RelaunchSession: CLI one-shot (cursor-agent). Steer = matar y relanzar con el mensaje nuevo sumado.
- FallbackSession: primero el primario; si falla con fallback (límite, red, key), pasa al secundario y se queda ahí.
- select_main_session: orden de Frontera: cursor-sdk -> grok warm (si la cuota de grok es > 40 %) -> cursor-agent
  grok-4.7-high-fast.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from pathlib import Path

from universal_bot.code_mode.cursor_sdk import _outcome_from, _parse_lines, sidecar_argv, sidecar_env
from universal_bot.code_mode.warm import TurnResult, make_session

LOW_GROK = 0.40
CURSOR_AGENT_MAIN_MODEL = "grok-4.7-high-fast"
HISTORY_TURNS = 6


class _History:
    def __init__(self, turns: int = HISTORY_TURNS):
        self.turns = turns
        self.items: list[tuple[str, str]] = []

    def prompt(self, text: str) -> str:
        if not self.items:
            return text
        keep = self.items[:1] + self.items[1:][-(self.turns - 1):]
        lines = ["Conversación hasta ahora (contexto, no la repitas):"]
        for asked, answered in keep:
            lines.append(f"[runtime/usuario]\n{asked}\n[MAIN]\n{answered}")
        return "\n\n".join(lines) + "\n\nMensaje actual:\n" + text

    def add(self, asked: str, answered: str) -> None:
        if answered:
            self.items.append((asked, answered))


def _kill(proc) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


class SidecarSession:
    def __init__(self, launcher, *, workdir, model: str = "composer-2.5", key_file=None, node_bin=None,
                 env: dict | None = None, grace_s: float = 15.0, tools=("read",)):
        self.launcher = Path(launcher)
        self.workdir = Path(workdir)
        self.model = model
        self.key_file = key_file
        self.node_bin = node_bin
        self.env = env
        self.grace_s = grace_s
        self.tools = list(tools)
        self.history = _History()
        self.turns = 0
        self.last_fallback = False
        self._turn_dir: Path | None = None
        self._lock = threading.Lock()

    def start(self):
        self.workdir.mkdir(parents=True, exist_ok=True)
        return self

    def alive(self) -> bool:
        return True

    def busy(self) -> bool:
        return self._turn_dir is not None

    def prompt(self, text: str, *, timeout_s: float = 120.0) -> TurnResult:
        self.turns += 1
        turn_dir = self.workdir / f"turn-{self.turns}"
        turn_dir.mkdir(parents=True, exist_ok=True)
        request = {
            "prompt": self.history.prompt(text), "model": self.model, "cwd": str(turn_dir), "timeout_s": timeout_s,
            "stream": False, "steer_file": str(turn_dir / "steer.jsonl"), "cancel_file": str(turn_dir / "cancel"), "tools": self.tools,
        }
        env = dict(self.env) if self.env is not None else sidecar_env(dict(os.environ), node_bin=self.node_bin)
        started = time.monotonic()
        with self._lock:
            self._turn_dir = turn_dir
        try:
            proc = subprocess.Popen(sidecar_argv(self.launcher, self.key_file), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True, cwd=turn_dir, env=env, start_new_session=True)
            try:
                stdout, stderr = proc.communicate(json.dumps(request), timeout=timeout_s + self.grace_s)
            except subprocess.TimeoutExpired:
                _kill(proc)
                proc.communicate()
                self.last_fallback = True
                return TurnResult(False, "timeout", "", self._ms(started), None, mode="sidecar", error="TIMEOUT")
        except OSError:
            self.last_fallback = True
            return TurnResult(False, "failed", "", self._ms(started), None, mode="sidecar", error="SDK_MISSING")
        finally:
            with self._lock:
                self._turn_dir = None
        lines = _parse_lines(stdout)
        steered = "live" if any(line.get("type") == "steer" and line.get("ok") for line in lines) else None
        outcome = _outcome_from(lines, stderr)
        self.last_fallback = bool(outcome.fallback) and not outcome.ok
        if outcome.ok:
            self.history.add(text, outcome.text)
            return TurnResult(True, "completed", outcome.text, self._ms(started), None, steered=steered,
                              usage=outcome.usage or {}, mode="sidecar")
        status = "cancelled" if outcome.code == "CANCELLED" else ("timeout" if outcome.code == "TIMEOUT" else "failed")
        return TurnResult(False, status, "", self._ms(started), None, steered=steered, mode="sidecar", error=outcome.code)

    def steer(self, text: str) -> str:
        with self._lock:
            if self._turn_dir is None:
                return "no_turn"
            with (self._turn_dir / "steer.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"text": text}, ensure_ascii=False) + "\n")
        return "live"

    def cancel(self) -> None:
        with self._lock:
            if self._turn_dir is not None:
                (self._turn_dir / "cancel").write_text("1", encoding="utf-8")

    def close(self) -> None:
        self.cancel()

    @staticmethod
    def _ms(started: float) -> int:
        return int((time.monotonic() - started) * 1000)


class RelaunchSession:
    """MAIN sobre un CLI one-shot: cada turno es un proceso; el steer lo mata y lo relanza con el mensaje nuevo."""

    RELAUNCH_NOTE = "Mensaje nuevo del usuario (cortó tu respuesta anterior; contestá a esto):"

    def __init__(self, argv_for, *, cwd, env=None, max_relaunches: int = 3):
        self.argv_for = argv_for
        self.cwd = Path(cwd)
        self.env = env
        self.max_relaunches = max_relaunches
        self.history = _History()
        self.last_fallback = False
        self._proc = None
        self._pending: list[str] = []
        self._lock = threading.Lock()

    def start(self):
        self.cwd.mkdir(parents=True, exist_ok=True)
        return self

    def alive(self) -> bool:
        return True

    def busy(self) -> bool:
        return self._proc is not None

    def prompt(self, text: str, *, timeout_s: float = 120.0) -> TurnResult:
        started = time.monotonic()
        full = self.history.prompt(text)
        asked = text
        steered = None
        relaunches = 0
        while True:
            with self._lock:
                self._proc = subprocess.Popen(self.argv_for(full), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                              cwd=self.cwd, env=self.env, start_new_session=True)
                proc = self._proc
            try:
                stdout, _ = proc.communicate(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                _kill(proc)
                proc.communicate()
                with self._lock:
                    self._proc = None
                return TurnResult(False, "timeout", "", SidecarSession._ms(started), None, steered=steered, mode="oneshot", error="TIMEOUT")
            with self._lock:
                pending, self._pending = self._pending, []
                self._proc = None
            if pending and relaunches < self.max_relaunches:
                relaunches += 1
                steered = "relaunch"
                extra = "\n".join(pending)
                full = f"{full}\n\n{self.RELAUNCH_NOTE}\n{extra}"
                asked = f"{asked}\n{extra}"
                continue
            if proc.returncode != 0 and not pending:
                return TurnResult(False, "failed", "", SidecarSession._ms(started), None, steered=steered, mode="oneshot",
                                  error=f"exit {proc.returncode}")
            reply = (stdout or "").strip()
            self.history.add(asked, reply)
            return TurnResult(True, "completed", reply, SidecarSession._ms(started), None, steered=steered, mode="oneshot")

    def steer(self, text: str) -> str:
        with self._lock:
            if self._proc is None:
                return "no_turn"
            self._pending.append(text)
            _kill(self._proc)
        return "relaunch"

    def cancel(self) -> None:
        with self._lock:
            if self._proc is not None:
                _kill(self._proc)

    def close(self) -> None:
        self.cancel()


class FallbackSession:
    def __init__(self, primary, secondary):
        self.primary = primary
        self.secondary = secondary
        self.active = primary
        self.events: list[str] = []
        self._first: str | None = None
        self._secondary_started = False

    def start(self):
        self.primary.start()
        return self

    def alive(self) -> bool:
        return True

    def busy(self) -> bool:
        return bool(getattr(self.active, "busy", lambda: False)())

    def prompt(self, text: str, *, timeout_s: float = 120.0) -> TurnResult:
        if self._first is None:
            self._first = text
        if self.active is self.primary:
            result = self.primary.prompt(text, timeout_s=timeout_s)
            if result.ok or result.status == "cancelled" or not getattr(self.primary, "last_fallback", True):
                return result
            self.events.append(f"fallback:{result.error}")
            self.active = self.secondary
            if text != self._first:
                text = f"Contexto inicial de esta charla:\n{self._first}\n\n{text}"
        if not self._secondary_started:
            self.secondary.start()
            self._secondary_started = True
        return self.secondary.prompt(text, timeout_s=timeout_s)

    def steer(self, text: str) -> str:
        return self.active.steer(text)

    def cancel(self) -> None:
        self.active.cancel()

    def close(self) -> None:
        self.primary.close()
        if self._secondary_started:
            self.secondary.close()


def cursor_agent_main_argv(cwd, model: str, prompt: str) -> list[str]:
    """MAIN en cursor-agent: modo ask (solo lectura), el trabajo lo hacen los workers."""
    return ["cursor-agent", "-p", "--output-format", "text", "--mode", "ask", "--model", model, "--trust",
            "--workspace", str(cwd), prompt]


def _grok_ok(quota) -> bool:
    if quota is None:
        return True
    try:
        return float(quota.grok_remaining()) > LOW_GROK
    except Exception:
        return True


def select_main_session(config, *, cwd, sidecar=None, key_file=None, quota=None, node_bin=None):
    """Devuelve una fábrica de sesiones del MAIN según config.main_cli y la cuota de grok."""
    cwd = Path(cwd)
    cli = config.main_cli
    grok_model = config.main_model if str(config.main_model).startswith("grok") else "grok-4.7"

    def cursor_agent():
        return RelaunchSession(lambda prompt: cursor_agent_main_argv(cwd, CURSOR_AGENT_MAIN_MODEL, prompt), cwd=cwd)

    def grok_or_cursor_agent():
        if _grok_ok(quota):
            return make_session("grok", grok_model, cwd=cwd, effort=config.main_effort)
        return cursor_agent()

    def factory():
        if cli in ("auto", "cursor-sdk"):
            if sidecar is not None and Path(sidecar).exists():
                primary = SidecarSession(sidecar, workdir=cwd / "sdk", model=config.main_sdk_model, key_file=key_file, node_bin=node_bin)
                return FallbackSession(primary, grok_or_cursor_agent())
            return grok_or_cursor_agent()
        if cli == "grok":
            return grok_or_cursor_agent()
        if cli == "cursor-agent":
            return cursor_agent()
        return make_session(cli, config.main_model, cwd=cwd, effort=config.main_effort)

    return factory

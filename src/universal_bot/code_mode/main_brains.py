"""Cerebros del MAIN.

- SidecarSession: cursor-sdk vía el sidecar (adapters/cursor_sdk). Un run por turno; el steer en vivo va por
  `steer_file` y el corte por `cancel_file`. La historia de la charla viaja en el prompt.
- ServeSidecarSession: cursor-sdk vía el sidecar en `--serve`: un proceso y un agente (`session_id`) por job. El
  agente guarda la charla, así que el prompt va sin historia; steer/cancel por request. Config optimizada
  (setting_sources [], sin MCP, allowlist de tools): ver evidence/sidecar-v2-bench.md.
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
import queue
import threading
import time
import uuid
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


class ServeSidecarSession:
    """MAIN cursor-sdk sobre un sidecar `--serve` de larga vida: se paga el arranque una vez por job."""

    GRACE_S = 15.0

    def __init__(self, launcher, *, workdir, model: str = "composer-2.5", key_file=None, node_bin=None,
                 env: dict | None = None, tools=("read",), setting_sources=(), mcp_servers=None):
        self.launcher = Path(launcher)
        self.workdir = Path(workdir)
        self.model = model
        self.key_file = key_file
        self.node_bin = node_bin
        self.env = env
        self.tools = list(tools)
        self.setting_sources = list(setting_sources)
        self.mcp_servers = mcp_servers
        self.history = _History()
        self.turns = 0
        self.last_fallback = False
        self.session_id = None
        self._proc = None
        self._fresh = True
        self._current = None
        self._steered: dict[str, bool] = {}
        self._waiters: dict[str, queue.Queue] = {}
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()

    # --- proceso -------------------------------------------------------
    def start(self):
        self.workdir.mkdir(parents=True, exist_ok=True)
        return self

    def _ensure_process(self) -> bool:
        if self._proc is not None and self._proc.poll() is None:
            return True
        env = dict(self.env) if self.env is not None else sidecar_env(dict(os.environ), node_bin=self.node_bin)
        argv = [str(self.launcher), "--serve"] + sidecar_argv(self.launcher, self.key_file)[1:]
        try:
            self._proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                          text=True, cwd=self.workdir, env=env, start_new_session=True, bufsize=1)
        except OSError:
            self._proc = None
            return False
        # Proceso nuevo = agente nuevo: sesión nueva y la historia vuelve a viajar en el primer prompt.
        self.session_id = f"main-{uuid.uuid4().hex[:12]}"
        self._fresh = True
        threading.Thread(target=self._reader, args=(self._proc,), daemon=True).start()
        return True

    def _reader(self, proc) -> None:
        for raw in proc.stdout:
            try:
                line = json.loads(raw)
            except ValueError:
                continue
            key = line.get("id")
            with self._lock:
                waiter = self._waiters.get(key)
            if waiter is not None:
                waiter.put(line)
        with self._lock:
            waiters = list(self._waiters.values())
        for waiter in waiters:
            waiter.put(None)

    def _send(self, message: dict) -> bool:
        try:
            with self._write_lock:
                self._proc.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
                self._proc.stdin.flush()
            return True
        except (OSError, ValueError, AttributeError):
            return False

    def _kill_process(self) -> None:
        if self._proc is not None:
            _kill(self._proc)

    # --- interfaz de sesión ---------------------------------------------
    def alive(self) -> bool:
        return True

    def busy(self) -> bool:
        return self._current is not None

    def prompt(self, text: str, *, timeout_s: float = 120.0) -> TurnResult:
        started = time.monotonic()
        if not self._ensure_process():
            self.last_fallback = True
            return TurnResult(False, "failed", "", self._ms(started), None, mode="sidecar-serve", error="SDK_MISSING")
        self.turns += 1
        run_id = f"t{self.turns}"
        prompt = self.history.prompt(text) if self._fresh else text
        request = {"op": "run", "id": run_id, "session_id": self.session_id, "prompt": prompt, "model": self.model,
                   "cwd": str(self.workdir), "timeout_s": timeout_s, "stream": False, "tools": self.tools,
                   "setting_sources": self.setting_sources, "mcp": bool(self.mcp_servers)}
        if self.mcp_servers:
            request["mcp_servers"] = self.mcp_servers
        waiter = queue.Queue()
        with self._lock:
            self._waiters[run_id] = waiter
            self._current = run_id
        steered = None
        try:
            if not self._send(request):
                self.last_fallback = True
                return TurnResult(False, "failed", "", self._ms(started), None, mode="sidecar-serve", error="SIDECAR_DIED")
            deadline = started + timeout_s + self.GRACE_S
            while True:
                try:
                    line = waiter.get(timeout=max(0.0, deadline - time.monotonic()))
                except queue.Empty:
                    self._send({"op": "cancel", "id": f"{run_id}-timeout", "target": run_id})
                    self.last_fallback = True
                    return TurnResult(False, "timeout", "", self._ms(started), None, steered=steered, mode="sidecar-serve", error="TIMEOUT")
                if line is None:
                    self.last_fallback = True
                    return TurnResult(False, "failed", "", self._ms(started), None, steered=steered, mode="sidecar-serve", error="SIDECAR_DIED")
                if line.get("type") in ("result", "error"):
                    break
        finally:
            with self._lock:
                self._waiters.pop(run_id, None)
                self._current = None
        with self._lock:
            if self._steered.pop(run_id, False):
                steered = "live"
        if line.get("type") == "result" and line.get("ok"):
            self.last_fallback = False
            self._fresh = False
            reply = line.get("text") or ""
            self.history.add(text, reply)
            return TurnResult(True, "completed", reply, self._ms(started), None, steered=steered,
                              usage=line.get("usage") or {}, mode="sidecar-serve")
        code = line.get("code")
        self.last_fallback = bool(line.get("fallback")) and code != "CANCELLED"
        status = "cancelled" if code == "CANCELLED" else ("timeout" if code == "TIMEOUT" else "failed")
        return TurnResult(False, status, "", self._ms(started), None, steered=steered, mode="sidecar-serve", error=code)

    def steer(self, text: str) -> str:
        with self._lock:
            target = self._current
            if target is None:
                return "no_turn"
            self._steered[target] = True
        self._send({"op": "steer", "id": f"{target}-s{uuid.uuid4().hex[:6]}", "target": target, "text": text})
        return "live"

    def cancel(self) -> None:
        with self._lock:
            target = self._current
        if target is not None:
            self._send({"op": "cancel", "id": f"{target}-c", "target": target})

    def close(self) -> None:
        proc = self._proc
        if proc is None:
            return
        self._send({"op": "shutdown"})
        try:
            proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _kill(proc)
            proc.wait(timeout=5)

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
    """Grok solo con cuota conocida y > 40 %. Sin lector o sin dato: no es cuota segura -> cursor-agent."""
    if quota is None:
        return False
    try:
        return float(quota.grok_remaining()) > LOW_GROK
    except Exception:
        return False


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
                if getattr(config, "main_sdk_serve", True):
                    primary = ServeSidecarSession(sidecar, workdir=cwd / "sdk", model=config.main_sdk_model, key_file=key_file,
                                                  node_bin=node_bin)
                else:
                    primary = SidecarSession(sidecar, workdir=cwd / "sdk", model=config.main_sdk_model, key_file=key_file,
                                             node_bin=node_bin)
                return FallbackSession(primary, grok_or_cursor_agent())
            return grok_or_cursor_agent()
        if cli == "grok":
            return grok_or_cursor_agent()
        if cli == "cursor-agent":
            return cursor_agent()
        if cli == "agy":
            from universal_bot.code_mode.agy_tui import AgyTuiSession, agy_tui_argv
            model = config.main_model if str(config.main_model).startswith("gemini") else "gemini-3.8-flash-low"
            return AgyTuiSession(agy_tui_argv(model), cwd=cwd / "agy")
        return make_session(cli, config.main_model, cwd=cwd, effort=config.main_effort)

    return factory

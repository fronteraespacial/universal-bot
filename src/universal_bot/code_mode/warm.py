"""Procesos fijos (warm) de los CLIs: codex app-server, opencode serve, agy stream-json y grok ACP.

Interfaz común: start / prompt / steer / cancel / close, más capacidades declaradas.
- Codex y OpenCode tienen steer en vivo (la instrucción entra en el mismo turno).
- Grok (ACP) no: steer = session/cancel + nuevo session/prompt con la instrucción.
- AGY no: steer = SIGINT + reanudar con la instrucción (si el proceso muere, se reinicia una vez).
`prompt` bloquea hasta el fin del turno; `steer` y `cancel` se llaman desde otro hilo.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import secrets
import signal
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

_ENV_KEEP = ("PATH", "HOME", "LANG", "LC_ALL", "TERM", "TMPDIR", "USER", "XDG_CONFIG_HOME", "XDG_DATA_HOME")
REPROMPT = "CAMBIO DE INSTRUCCIÓN (reemplaza lo que estabas haciendo, el contexto anterior sigue valiendo): {text}"
RESUME = "Tarea original: {original}\n" + REPROMPT


class WarmError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


@dataclass(frozen=True)
class Capabilities:
    supports_live_steer: bool
    steer_strategy: str  # live | cancel_reprompt | interrupt_resume
    invocation: str
    cancel: str


CAPABILITIES = {
    "codex": Capabilities(True, "live", "codex app-server (JSON-RPC stdio)", "turn/interrupt"),
    "opencode": Capabilities(True, "live", "opencode serve (HTTP + SSE /api/*)", "POST /api/session/{id}/interrupt"),
    "grok": Capabilities(False, "cancel_reprompt", "grok agent stdio (ACP JSON-RPC)", "session/cancel"),
    "agy": Capabilities(False, "interrupt_resume", "agy --input-format stream-json", "SIGINT"),
}


@dataclass(frozen=True)
class TurnResult:
    ok: bool
    status: str  # completed | cancelled | timeout | failed
    text: str
    duration_ms: int
    first_token_ms: int | None
    steered: str | None = None
    usage: dict = field(default_factory=dict)
    mode: str = "warm"
    error: str | None = None


def warm_argv(cli: str, model: str, effort: str = "low", *, port: int | None = None) -> list[str]:
    if cli == "codex":
        return ["codex", "app-server"]
    if cli == "grok":
        return ["grok", "agent", "-m", model, "--effort", effort, "--always-approve", "stdio"]
    if cli == "agy":
        return [
            "agy", "--input-format", "stream-json", "--output-format", "stream-json",
            "--model", model, "--dangerously-skip-permissions",
        ]
    if cli == "opencode":
        return ["opencode", "serve", "--hostname", "127.0.0.1", "--port", str(port or 0)]
    raise WarmError("unknown_cli", cli)


def _env(extra: dict | None) -> dict:
    env = {name: os.environ[name] for name in _ENV_KEEP if name in os.environ}
    env.update(extra or {})
    return env


class _Turn:
    """Estado del turno en curso, compartido entre el hilo lector y el que espera."""

    def __init__(self, text: str):
        self.text = text
        self.started = time.monotonic()
        self.first = None
        self.chunks: list[str] = []
        self.done = threading.Event()
        self.status = None
        self.usage: dict = {}
        self.error = None
        self.cancel_requested = False
        self.steer_text: str | None = None
        self.steered: str | None = None

    def add(self, piece: str) -> None:
        if not piece:
            return
        if self.first is None:
            self.first = time.monotonic()
        self.chunks.append(piece)

    def finish(self, status: str, error: str | None = None) -> None:
        self.status = status
        self.error = error
        self.done.set()


class _WarmBase:
    cli = ""

    def __init__(self, model: str, *, cwd, command=None, env=None, effort: str = "low"):
        self.model = model
        self.cwd = Path(cwd)
        self.effort = effort
        self.command = list(command) if command else None
        self.extra_env = dict(env or {})
        self.proc: subprocess.Popen | None = None
        self.restarts = 0
        self.streamed_chars = 0
        self.last_used = time.monotonic()
        self._turn: _Turn | None = None
        self._lock = threading.Lock()
        self._turn_lock = threading.Lock()

    @property
    def capabilities(self) -> Capabilities:
        return CAPABILITIES[self.cli]

    @property
    def pid(self) -> int | None:
        return self.proc.pid if self.proc else None

    @property
    def argv(self) -> list[str]:
        return self._argv()

    def _argv(self) -> list[str]:
        base = warm_argv(self.cli, self.model, self.effort)
        return self.command + base[1:] if self.command else base

    def __repr__(self) -> str:
        return f"<{type(self).__name__} cli={self.cli} model={self.model} pid={self.pid}>"

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def wait_dead(self, timeout: float) -> None:
        if self.proc is not None:
            try:
                self.proc.wait(timeout)
            except subprocess.TimeoutExpired:
                pass

    def _spawn(self, argv, *, stdin=True) -> None:
        self.proc = subprocess.Popen(
            argv,
            cwd=self.cwd,
            env=_env(self.extra_env),
            stdin=subprocess.PIPE if stdin else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            start_new_session=True,
        )

    def close(self) -> None:
        proc, self.proc = self.proc, None
        if self._turn is not None and not self._turn.done.is_set():
            self._turn.finish("cancelled", "closed")
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except OSError:
            pass
        proc.terminate()
        try:
            proc.wait(3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(3)

    # --- turnos ---------------------------------------------------------
    def prompt(self, text: str, *, timeout_s: float = 300.0) -> TurnResult:
        if not self.alive():
            raise WarmError("not_running")
        with self._turn_lock:
            self.last_used = time.monotonic()
            turn = _Turn(text)
            self._turn = turn
            self.streamed_chars = 0
            self._send_prompt(turn, text)
            deadline = time.monotonic() + timeout_s
            while True:
                left = deadline - time.monotonic()
                if left <= 0 or turn.done.wait(min(left, 0.2)):
                    pass
                if turn.done.is_set():
                    follow = self._after_turn(turn)
                    if follow is None:
                        break
                    turn = follow
                    self._turn = turn
                    continue
                if time.monotonic() >= deadline:
                    self._cancel_turn(turn)
                    turn.done.wait(5)
                    turn.status = "timeout"
                    break
                if not self.alive():
                    turn.finish("failed", "process_died")
                    break
            self._turn = None
            self.last_used = time.monotonic()
            first = turn.first if turn.first is not None else None
            ok = turn.status == "completed"
            result = TurnResult(
                ok=ok,
                status=turn.status or "failed",
                text="".join(turn.chunks),
                duration_ms=int((time.monotonic() - self._origin(turn)) * 1000),
                first_token_ms=None if first is None else int((first - self._origin(turn)) * 1000),
                steered=turn.steered,
                usage=dict(turn.usage),
                error=turn.error,
            )
            if turn.error == "process_died":
                raise WarmError("process_died", self.cli)
            return result

    def _origin(self, turn: _Turn) -> float:
        return getattr(turn, "origin", turn.started)

    def _follow_up(self, turn: _Turn, text: str) -> _Turn:
        nxt = _Turn(text)
        nxt.origin = self._origin(turn)
        nxt.steered = self.capabilities.steer_strategy
        return nxt

    def _after_turn(self, turn: _Turn):
        """Turno terminado: si había un steer pendiente (cancel+reprompt), arranca el turno siguiente."""
        if turn.steer_text is None or turn.status != "cancelled":
            return None
        nxt = self._follow_up(turn, REPROMPT.format(text=turn.steer_text))
        self._turn = nxt
        self.streamed_chars = 0
        self._send_prompt(nxt, nxt.text)
        return nxt

    def steer(self, text: str) -> str:
        turn = self._turn
        if turn is None or turn.done.is_set():
            return "no_turn"
        return self._steer(turn, text)

    def cancel(self) -> None:
        turn = self._turn
        if turn is None or turn.done.is_set():
            return
        turn.cancel_requested = True
        self._cancel_turn(turn)

    # hooks por CLI
    def start(self):  # pragma: no cover - abstracto
        raise NotImplementedError

    def _send_prompt(self, turn: _Turn, text: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def _cancel_turn(self, turn: _Turn) -> None:  # pragma: no cover
        raise NotImplementedError

    def _steer(self, turn: _Turn, text: str) -> str:  # pragma: no cover
        raise NotImplementedError

    def _on_chunk(self, piece: str) -> None:
        turn = self._turn
        if turn is not None and piece:
            turn.add(piece)
            self.streamed_chars += len(piece)


class _JsonLines(_WarmBase):
    """Proceso con JSON por línea en stdin/stdout y un hilo lector."""

    def _start_process(self) -> None:
        self._spawn(self._argv())
        self._ids = 0
        self._waiting: dict[int, dict] = {}
        self._cv = threading.Condition()
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self) -> None:
        proc = self.proc
        for line in proc.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if isinstance(msg, dict) and "id" in msg and ("result" in msg or "error" in msg) and "method" not in msg:
                with self._cv:
                    self._waiting[msg["id"]] = msg
                    self._cv.notify_all()
                self._on_response(msg)
                continue
            self._on_message(msg)
        turn = self._turn
        if turn is not None and not turn.done.is_set():
            turn.finish("failed", "process_died")

    def _write(self, msg: dict) -> None:
        try:
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()
        except (OSError, AttributeError) as exc:
            raise WarmError("process_died", type(exc).__name__) from exc

    def _request(self, method: str, params: dict, *, rpc: bool = False) -> int:
        with self._lock:
            self._ids += 1
            mid = self._ids
        msg = {"id": mid, "method": method, "params": params}
        if rpc:
            msg["jsonrpc"] = "2.0"
        self._write(msg)
        return mid

    def _notify(self, method: str, params: dict, *, rpc: bool = False) -> None:
        msg = {"method": method, "params": params}
        if rpc:
            msg["jsonrpc"] = "2.0"
        self._write(msg)

    def _wait(self, mid: int, timeout: float = 60.0) -> dict:
        deadline = time.monotonic() + timeout
        with self._cv:
            while mid not in self._waiting:
                left = deadline - time.monotonic()
                if left <= 0 or not self.alive():
                    raise WarmError("start_failed" if left > 0 else "rpc_timeout", f"id={mid}")
                self._cv.wait(min(left, 0.2))
            return self._waiting.pop(mid)

    def _on_response(self, msg: dict) -> None:
        pass

    def _on_message(self, msg: dict) -> None:
        pass


class CodexAppServer(_JsonLines):
    cli = "codex"

    def start(self):
        self._start_process()
        self._wait(self._request("initialize", {"clientInfo": {"name": "universal_bot", "title": "ub", "version": "0.1"}}))
        self._notify("initialized", {})
        res = self._wait(self._request("thread/start", {
            "model": self.model, "cwd": str(self.cwd), "approvalPolicy": "never", "sandbox": "workspace-write",
        }))
        if "error" in res:
            raise WarmError("start_failed", str(res["error"].get("message", ""))[:200])
        self.thread_id = res["result"]["thread"]["id"]
        self.turn_id = None
        return self

    def _send_prompt(self, turn, text):
        mid = self._request("turn/start", {"threadId": self.thread_id, "input": [{"type": "text", "text": text}], "effort": self.effort})
        res = self._wait(mid)
        if "error" in res:
            turn.finish("failed", str(res["error"].get("message", ""))[:200])
            return
        self.turn_id = res["result"]["turn"]["id"]

    def _on_message(self, msg):
        method = msg.get("method")
        params = msg.get("params") or {}
        if method == "item/agentMessage/delta":
            self._on_chunk(str(params.get("delta") or ""))
        elif method == "turn/completed":
            turn = self._turn
            if turn is None:
                return
            status = (params.get("turn") or {}).get("status")
            usage = params.get("usage") or (params.get("turn") or {}).get("usage") or {}
            turn.usage = usage if isinstance(usage, dict) else {}
            if status == "completed":
                turn.finish("completed")
            elif status == "interrupted":
                turn.finish("cancelled")
            else:
                turn.finish("failed", str(status))

    def _steer(self, turn, text):
        turn.steered = "live"  # antes de mandar: el turno puede cerrar antes que llegue la respuesta
        res = self._wait(self._request("turn/steer", {
            "threadId": self.thread_id, "expectedTurnId": self.turn_id, "input": [{"type": "text", "text": text}],
        }), timeout=15)
        if "error" in res:
            turn.steered = None
            return "rejected"
        return "live"

    def _cancel_turn(self, turn):
        if self.turn_id:
            self._request("turn/interrupt", {"threadId": self.thread_id, "turnId": self.turn_id})


class GrokAcp(_JsonLines):
    cli = "grok"

    def start(self):
        self._start_process()
        init = self._wait(self._request("initialize", {
            "protocolVersion": 1, "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False},
        }, rpc=True))
        if "error" in init:
            raise WarmError("start_failed", "initialize")
        res = self._wait(self._request("session/new", {"cwd": str(self.cwd), "mcpServers": [], "_meta": {"yoloMode": True}}, rpc=True))
        if "error" in res:
            raise WarmError("start_failed", "session/new")
        self.session_id = res["result"]["sessionId"]
        self._prompt_id = None
        return self

    def _send_prompt(self, turn, text):
        self._prompt_id = self._request("session/prompt", {"sessionId": self.session_id, "prompt": [{"type": "text", "text": text}]}, rpc=True)

    def _on_response(self, msg):
        turn = self._turn
        if turn is None or msg.get("id") != self._prompt_id:
            return
        if "error" in msg:
            turn.finish("failed", str(msg["error"].get("message", ""))[:200])
            return
        result = msg.get("result") or {}
        usage = ((result.get("_meta") or {}).get("usage")) or {}
        turn.usage = usage if isinstance(usage, dict) else {}
        reason = result.get("stopReason")
        turn.finish("cancelled" if reason == "cancelled" else "completed" if reason == "end_turn" else "failed",
                    None if reason in ("end_turn", "cancelled") else str(reason))

    def _on_message(self, msg):
        if msg.get("method") != "session/update":
            return
        update = (msg.get("params") or {}).get("update") or {}
        if update.get("sessionUpdate") == "agent_message_chunk":
            content = update.get("content") or {}
            self._on_chunk(str(content.get("text") or ""))

    def _steer(self, turn, text):
        turn.steer_text = text
        self._cancel_turn(turn)
        return "cancel_reprompt"

    def _cancel_turn(self, turn):
        self._notify("session/cancel", {"sessionId": self.session_id}, rpc=True)


class AgyStream(_JsonLines):
    cli = "agy"

    def start(self):
        self._start_process()
        return self

    def _send_prompt(self, turn, text):
        self._write({"event": "user", "message": {"content": text}})

    def _on_message(self, msg):
        update = msg.get("step_update") or {}
        if update.get("step_type") == "agent_response":
            self._on_chunk(str(update.get("text_delta") or ""))
        if msg.get("event") == "result":
            turn = self._turn
            if turn is None:
                return
            status = (msg.get("result") or {}).get("status")
            if status == "SUCCESS":
                turn.finish("completed")
            elif status == "INTERRUPTED":
                turn.finish("cancelled")
            else:
                turn.finish("failed", str(status))

    def _steer(self, turn, text):
        turn.steer_text = text
        self._cancel_turn(turn)
        return "interrupt_resume"

    def _cancel_turn(self, turn):
        if self.alive():
            try:
                os.kill(self.proc.pid, signal.SIGINT)
            except ProcessLookupError:
                pass

    def prompt(self, text, *, timeout_s=300.0):
        try:
            return super().prompt(text, timeout_s=timeout_s)
        except WarmError as exc:
            turn = getattr(self, "_died_turn", None)
            if exc.code != "process_died" or turn is None or self.restarts >= 1:
                raise
            # SIGINT mató el proceso: un reinicio y se retoma con la instrucción nueva.
            self.restarts += 1
            self._died_turn = None
            self.proc = None
            self.start()
            result = super().prompt(RESUME.format(original=turn.text, text=turn.steer_text), timeout_s=timeout_s)
            return TurnResult(
                ok=result.ok, status=result.status, text=result.text,
                duration_ms=int((time.monotonic() - turn.started) * 1000),
                first_token_ms=result.first_token_ms, steered="interrupt_resume",
                usage=result.usage, error=result.error,
            )

    def _read(self):
        super()._read()
        turn = self._turn
        if turn is not None and turn.steer_text is not None:
            self._died_turn = turn


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class OpenCodeServe(_WarmBase):
    cli = "opencode"

    def __init__(self, model, **kwargs):
        super().__init__(model, **kwargs)
        self._password = secrets.token_urlsafe(32)
        self.port = None

    def _argv(self):
        base = warm_argv("opencode", self.model, self.effort, port=self.port)
        return self.command + base[1:] if self.command else base

    def __repr__(self):
        return f"<OpenCodeServe model={self.model} port={self.port} pid={self.pid}>"

    def start(self):
        import queue

        self.port = _free_port()
        self.extra_env = {**self.extra_env, "OPENCODE_SERVER_PASSWORD": self._password}
        self._spawn(self._argv(), stdin=False)
        lines: "queue.Queue[str | None]" = queue.Queue()
        proc = self.proc

        def pump():
            for raw in proc.stdout:
                lines.put(raw)
            lines.put(None)

        threading.Thread(target=pump, daemon=True).start()
        self.base = None
        deadline = time.monotonic() + 30
        while self.base is None and time.monotonic() < deadline:
            try:
                line = lines.get(timeout=0.5)
            except queue.Empty:
                continue
            if line is None:
                raise WarmError("start_failed", "opencode serve terminó")
            if line.startswith("server listening on "):
                self.base = line.split("server listening on ", 1)[1].strip()
        if not self.base:
            raise WarmError("start_failed", "sin url")
        # Si el server no tomó la variable, imprime su password en la línea siguiente: se usa sin loguearla.
        try:
            line = lines.get(timeout=1.0)
        except queue.Empty:
            line = None
        if line and line.startswith("server password "):
            self._password = line.split("server password ", 1)[1].strip()
        self._events = threading.Thread(target=self._sse, daemon=True)
        self._events.start()
        provider, _, model_id = self.model.partition("/")
        res = self._http("POST", "/api/session", {
            "title": "universal_bot", "model": {"id": model_id or provider, "providerID": provider if model_id else "opencode"},
            "location": {"directory": str(self.cwd)}, "permissions": [{"action": "*", "resource": "*", "effect": "allow"}],
        })
        self.session_id = res["data"]["id"]
        return self

    def _headers(self):
        token = base64.b64encode(f"opencode:{self._password}".encode()).decode()
        return {"Authorization": "Basic " + token, "Content-Type": "application/json"}

    def _http(self, method, path, body=None, timeout=30):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, method=method, headers=self._headers(), data=data)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            raise WarmError("http_error", f"{method} {path} -> {exc.code}") from None
        except (urllib.error.URLError, OSError) as exc:
            raise WarmError("http_error", f"{method} {path} -> {type(exc).__name__}") from None
        return json.loads(raw or b"null")

    def _sse(self):
        req = urllib.request.Request(self.base + "/api/event", headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=3600) as stream:
                for raw in stream:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    try:
                        event = json.loads(line[5:])
                    except ValueError:
                        continue
                    self._on_event(event)
        except (OSError, urllib.error.URLError):
            turn = self._turn
            if turn is not None and not turn.done.is_set() and not self.alive():
                turn.finish("failed", "process_died")

    def _on_event(self, event):
        props = event.get("properties") or {}
        sid = props.get("sessionID") or props.get("sessionId")
        if sid is not None and sid != getattr(self, "session_id", None):
            return
        if sid is None and getattr(self, "session_id", "") not in json.dumps(event):
            return
        kind = event.get("type", "")
        turn = self._turn
        if turn is None:
            return
        if kind == "session.text.delta":
            piece = props.get("delta") or props.get("text")
            if isinstance(piece, str):
                self._on_chunk(piece)
            else:
                # forma desconocida: cuenta como primer token; el texto sale de los mensajes al final
                if turn.first is None:
                    turn.first = time.monotonic()
                self.streamed_chars += 1
        elif kind == "session.execution.succeeded":
            final = self._last_assistant_text()
            if final is not None:
                turn.chunks = [final]
            turn.finish("completed")
        elif kind == "session.execution.failed":
            turn.finish("cancelled" if turn.cancel_requested else "failed", None if turn.cancel_requested else "failed")

    def _last_assistant_text(self) -> str | None:
        """El texto final autoritativo: el mensaje assistant más nuevo (la API lista del más nuevo al más viejo)."""
        try:
            res = self._http("GET", f"/api/session/{self.session_id}/message", timeout=10)
        except WarmError:
            return None
        for message in (res or {}).get("data") or []:
            if message.get("type") != "assistant":
                continue
            parts = [c.get("text", "") for c in message.get("content") or [] if c.get("type") == "text"]
            return "".join(parts)
        return None

    def _send_prompt(self, turn, text):
        self._http("POST", f"/api/session/{self.session_id}/prompt", {"text": text})

    def _steer(self, turn, text):
        turn.steered = "live"
        res = self._http("POST", f"/api/session/{self.session_id}/prompt", {"text": text, "delivery": "steer"})
        if ((res or {}).get("data") or {}).get("delivery") != "steer":
            turn.steered = None
            return "rejected"
        return "live"

    def _cancel_turn(self, turn):
        turn.cancel_requested = True
        self._http("POST", f"/api/session/{self.session_id}/interrupt")



_CLASSES = {"codex": CodexAppServer, "grok": GrokAcp, "agy": AgyStream, "opencode": OpenCodeServe}


def make_session(cli: str, model: str, *, cwd, command=None, env=None, effort: str = "low"):
    try:
        cls = _CLASSES[cli]
    except KeyError:
        raise WarmError("unknown_cli", cli) from None
    return cls(model, cwd=cwd, command=command, env=env, effort=effort)


class WarmPool:
    """Un proceso caliente por (cli, modelo). Cierra por inactividad y reinicia una sola vez si muere."""

    def __init__(self, factory, *, idle_timeout_s: float = 600.0, clock=time.monotonic, max_restarts: int = 1):
        self.factory = factory
        self.idle_timeout_s = idle_timeout_s
        self.clock = clock
        self.max_restarts = max_restarts
        self._sessions: dict[tuple[str, str], object] = {}
        self._last: dict[tuple[str, str], float] = {}
        self._restarts: dict[tuple[str, str], int] = {}
        self._broken: set[tuple[str, str]] = set()
        self.events: list[dict] = []
        self._lock = threading.Lock()

    def session(self, cli: str, model: str):
        key = (cli, model)
        with self._lock:
            if key in self._broken:
                raise WarmError("restart_exhausted", f"{cli}/{model}")
            current = self._sessions.get(key)
            if current is not None and current.alive():
                self._last[key] = self.clock()
                return current
            if current is not None:
                used = self._restarts.get(key, 0)
                if used >= self.max_restarts:
                    self._broken.add(key)
                    self._sessions.pop(key, None)
                    self.events.append({"event": "restart_exhausted", "cli": cli, "model": model})
                    log.warning("warm %s/%s murió otra vez; queda en one-shot", cli, model)
                    raise WarmError("restart_exhausted", f"{cli}/{model}")
                self._restarts[key] = used + 1
                self.events.append({"event": "restart", "cli": cli, "model": model})
                current.close()
            fresh = self.factory(cli, model)
            fresh.start()
            self._sessions[key] = fresh
            self._last[key] = self.clock()
            return fresh

    def run(self, cli: str, model: str, text: str, *, timeout_s: float = 300.0, oneshot=None) -> TurnResult:
        try:
            session = self.session(cli, model)
            result = session.prompt(text, timeout_s=timeout_s)
            self._last[(cli, model)] = self.clock()
            return result
        except WarmError as exc:
            if oneshot is None:
                raise
            self.events.append({"event": "fallback_oneshot", "cli": cli, "model": model, "reason": exc.code})
            started = time.monotonic()
            text_out = oneshot(cli, model, text)
            elapsed = int((time.monotonic() - started) * 1000)
            return TurnResult(True, "completed", str(text_out), elapsed, None, mode="oneshot")

    def reap_idle(self) -> list[tuple[str, str]]:
        now = self.clock()
        closed = []
        with self._lock:
            for key, session in list(self._sessions.items()):
                if now - self._last.get(key, now) > self.idle_timeout_s:
                    session.close()
                    del self._sessions[key]
                    closed.append(key)
        return closed

    def close(self) -> None:
        with self._lock:
            for session in self._sessions.values():
                session.close()
            self._sessions.clear()

"""Spike: MAIN de agy por la TUI interactiva, manejada con tmux.

Por qué: con `agy --input-format stream-json` el MAIN no queda libre (no hay `result` mientras vive el subagente).
En la TUI el MAIN delega, vuelve al prompt `>` y lo que se escribe le llega al subagente ("Messaged 1 subagent").

Cómo: una sesión tmux propia (socket aparte) por MAIN. `prompt` escribe el texto + Enter y espera a que la pantalla
vuelva al prompt y quede quieta `settle_s`; la respuesta es lo nuevo entre la línea tecleada y el prompt.
`steer` escribe igual aunque haya un subagente corriendo. `cancel` manda Escape; `close` mata la sesión.

Queued Messages: en vez de cambiar el settings.json global a `send-immediately` (lo comparten otros usos de agy), el
steer con turno vivo usa alt+m, que manda el mensaje con el modo opuesto al configurado (`Queue` -> inmediato).
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import time
import uuid
from pathlib import Path

from universal_bot.code_mode.warm import TurnResult

PROMPT_RE = re.compile(r"^\s*>\s?.*$")
TRUST_TEXT = "Do you trust the contents of this project?"
NOTICE_TEXT = "esc to dismiss"
_CHROME = re.compile(r"^[\s─━┃│]*$")


def agy_tui_argv(model: str) -> list[str]:
    return ["agy", "--model", model, "--dangerously-skip-permissions"]


class AgyTuiSession:
    def __init__(self, argv, *, cwd, settle_s: float = 0.8, poll_s: float = 0.1, prompt_re=PROMPT_RE,
                 width: int = 200, height: int = 60, history: int = 5000):
        self.argv = list(argv)
        self.cwd = Path(cwd)
        self.settle_s = settle_s
        self.poll_s = poll_s
        self.prompt_re = prompt_re
        self.width = width
        self.height = height
        self.history = history
        self.socket = f"ub-agy-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self.name = "main"
        self._busy = False

    # --- tmux ---------------------------------------------------------
    def _tmux(self, *args, check=True) -> str:
        done = subprocess.run(["tmux", "-L", self.socket, *args], capture_output=True, text=True, check=False)
        if check and done.returncode != 0:
            raise RuntimeError(f"tmux {args[0]} falló")
        return done.stdout

    def start(self):
        self.cwd.mkdir(parents=True, exist_ok=True)
        self._tmux("new-session", "-d", "-s", self.name, "-x", str(self.width), "-y", str(self.height),
                   "-c", str(self.cwd), " ".join(shlex.quote(part) for part in self.argv))
        self._tmux("set-option", "-t", self.name, "history-limit", str(self.history), check=False)
        deadline = time.monotonic() + 30
        trusted = False
        while time.monotonic() < deadline:
            lines = self._lines()
            if not trusted and any(TRUST_TEXT in line for line in lines):
                # Una sola vez: el diálogo queda en el scrollback y re-contestarlo mandaría Enters de más.
                self._tmux("send-keys", "-t", self.name, "Enter")
                trusted = True
                time.sleep(self.poll_s)
                continue
            if self._at_prompt(lines):
                break
            time.sleep(self.poll_s)
        self._wait_ready(time.monotonic() + 10)
        if any(NOTICE_TEXT in line for line in self._lines()):
            # Aviso de Verbosity (u otro "esc to dismiss"): se cierra una vez para que no tape la caja.
            self._tmux("send-keys", "-t", self.name, "Escape", check=False)
            time.sleep(max(self.poll_s, 0.3))
        return self

    def alive(self) -> bool:
        return subprocess.run(["tmux", "-L", self.socket, "has-session", "-t", self.name],
                              capture_output=True).returncode == 0

    def busy(self) -> bool:
        return self._busy

    def screen(self) -> str:
        return self._tmux("capture-pane", "-p", "-J", "-t", self.name, "-S", f"-{self.history}", check=False)

    def _type(self, text: str) -> None:
        self._tmux("send-keys", "-t", self.name, "-l", text.replace("\n", " "))
        self._tmux("send-keys", "-t", self.name, "Enter")

    # --- turnos -------------------------------------------------------
    def _lines(self) -> list[str]:
        lines = [line.rstrip() for line in self.screen().splitlines()]
        while lines and not lines[-1]:
            lines.pop()
        return lines

    def _at_prompt(self, lines: list[str]) -> bool:
        """Caja de entrada vacía (`>` solo) entre las últimas líneas: la TUI real dibuja separadores y un pie abajo."""
        tail = [line for line in lines if line.strip()][-4:]
        return any(line.strip() == ">" for line in tail)

    def _wait_ready(self, deadline: float, *, after: list[str] | None = None) -> list[str] | None:
        last, since = None, time.monotonic()
        while time.monotonic() < deadline:
            lines = self._lines()
            if lines != last:
                last, since = lines, time.monotonic()
            elif lines != after and self._at_prompt(lines) and time.monotonic() - since >= self.settle_s:
                return lines
            time.sleep(self.poll_s)
        return None

    def prompt(self, text: str, *, timeout_s: float = 120.0) -> TurnResult:
        started = time.monotonic()
        snapshot = self._lines()
        before = len(snapshot)
        self._busy = True
        try:
            self._type(text)
            lines = self._wait_ready(started + timeout_s, after=snapshot)
        finally:
            self._busy = False
        ms = int((time.monotonic() - started) * 1000)
        if lines is None:
            return TurnResult(False, "timeout", "", ms, None, mode="tui", error="TIMEOUT")
        return TurnResult(True, "completed", self._reply(lines, before, text), ms, None, mode="tui")

    def _reply(self, lines: list[str], before: int, typed: str) -> str:
        new = lines[max(before - 1, 0):]
        flat = typed.replace("\n", " ").strip()
        for index, line in enumerate(new):
            if flat and flat in line:
                new = new[index + 1:]
                break
        body = []
        for line in new:
            if line.strip() == ">":
                break
            if line.strip() and not _CHROME.match(line):
                body.append(line.strip())
        return "\n".join(body).strip()

    def steer(self, text: str) -> str:
        """Con el MAIN libre, Enter. Con un turno vivo, alt+m: manda ya (Send Immediately) aunque la config global
        siga en `Queue`, sin tocar el settings.json que comparten otros usos de agy."""
        if not self.alive():
            return "no_turn"
        if self._busy:
            self._tmux("send-keys", "-t", self.name, "-l", text.replace("\n", " "))
            self._tmux("send-keys", "-t", self.name, "M-m")
        else:
            self._type(text)
        return "live"

    def cancel(self) -> None:
        if self.alive():
            self._tmux("send-keys", "-t", self.name, "Escape", check=False)

    def socket_path(self) -> Path:
        base = os.environ.get("TMUX_TMPDIR") or "/tmp"
        return Path(base) / f"tmux-{os.getuid()}" / self.socket

    def close(self) -> None:
        if self.alive():
            self._tmux("kill-server", check=False)
        self.socket_path().unlink(missing_ok=True)

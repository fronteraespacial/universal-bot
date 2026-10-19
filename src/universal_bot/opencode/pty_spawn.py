"""PTY spawn helper for ``opencode run --auto`` (Linux pty; Windows optional)."""

from __future__ import annotations

import os
import select
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import BinaryIO


class PtyUnavailable(RuntimeError):
    """Raised when a PTY is required but unavailable on this platform."""


def pty_available() -> bool:
    """True when this process can open a PTY for child spawn."""
    if sys.platform == "win32":
        try:
            import winpty  # type: ignore  # noqa: F401

            return True
        except ImportError:
            try:
                import pywinpty  # type: ignore  # noqa: F401

                return True
            except ImportError:
                return False
    try:
        import pty  # noqa: F401

        return True
    except ImportError:
        return False


@dataclass
class PtyResult:
    returncode: int
    stdout: str
    timed_out: bool = False


def spawn_with_pty(
    argv: Sequence[str],
    *,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    timeout_s: float = 1800.0,
    require_pty: bool = True,
    on_line: Callable[[str], None] | None = None,
) -> PtyResult:
    """Run ``argv`` attached to a PTY so ``--auto`` does not stall.

    Linux/macOS: ``pty.openpty``.
    Windows: optional ``pywinpty`` / ``winpty``; if missing and ``require_pty``,
    raises :class:`PtyUnavailable` (caller should fall back to serve-only /
    no ``--auto``). If ``require_pty`` is False, falls back to pipes.
    """
    if sys.platform == "win32":
        return _spawn_windows(
            argv,
            cwd=cwd,
            env=env,
            timeout_s=timeout_s,
            require_pty=require_pty,
            on_line=on_line,
        )
    return _spawn_posix(
        argv,
        cwd=cwd,
        env=env,
        timeout_s=timeout_s,
        require_pty=require_pty,
        on_line=on_line,
    )


def _spawn_posix(
    argv: Sequence[str],
    *,
    cwd: str | None,
    env: Mapping[str, str] | None,
    timeout_s: float,
    require_pty: bool,
    on_line: Callable[[str], None] | None,
) -> PtyResult:
    cli_env = dict(env) if env is not None else os.environ.copy()
    cli_env.setdefault("TERM", "xterm-256color")
    cli_env.setdefault("CI", "1")

    try:
        import pty
    except ImportError:
        if require_pty:
            raise PtyUnavailable("posix pty module unavailable")
        return _spawn_pipes(argv, cwd=cwd, env=cli_env, timeout_s=timeout_s, on_line=on_line)

    master_fd, slave_fd = pty.openpty()
    buf = ""
    chunks: list[str] = []
    timed_out = False
    try:
        proc = subprocess.Popen(
            list(argv),
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=cwd,
            env=cli_env,
            close_fds=True,
        )
        os.close(slave_fd)
        slave_fd = -1
        deadline = time.monotonic() + max(1.0, timeout_s)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    pass
                break
            ready, _, _ = select.select([master_fd], [], [], min(1.0, remaining))
            if not ready:
                if proc.poll() is not None:
                    break
                continue
            try:
                chunk = os.read(master_fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            text = chunk.decode("utf-8", errors="replace")
            chunks.append(text)
            buf += text
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                if on_line:
                    on_line(line)
        if not timed_out:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                timed_out = True
                proc.kill()
                proc.wait(timeout=5)
        if buf and on_line:
            on_line(buf)
        return PtyResult(
            returncode=int(proc.returncode if proc.returncode is not None else -1),
            stdout="".join(chunks),
            timed_out=timed_out,
        )
    finally:
        if slave_fd >= 0:
            try:
                os.close(slave_fd)
            except OSError:
                pass
        try:
            os.close(master_fd)
        except OSError:
            pass


def _spawn_windows(
    argv: Sequence[str],
    *,
    cwd: str | None,
    env: Mapping[str, str] | None,
    timeout_s: float,
    require_pty: bool,
    on_line: Callable[[str], None] | None,
) -> PtyResult:
    cli_env = dict(env) if env is not None else os.environ.copy()
    # Prefer pywinpty if present; otherwise surface serve-only fallback.
    pty_mod = None
    for name in ("winpty", "pywinpty"):
        try:
            pty_mod = __import__(name)
            break
        except ImportError:
            continue
    if pty_mod is None:
        if require_pty:
            raise PtyUnavailable(
                "Windows ConPTY/pywinpty unavailable; use serve-only fallback "
                "(omit --auto or install pywinpty)"
            )
        return _spawn_pipes(argv, cwd=cwd, env=cli_env, timeout_s=timeout_s, on_line=on_line)

    # Minimal ConPTY-style path: if the module exposes PtyProcess, use it;
    # otherwise fall back to pipes when allowed.
    PtyProcess = getattr(pty_mod, "PtyProcess", None) or getattr(
        getattr(pty_mod, "ptyprocess", None), "PtyProcess", None
    )
    if PtyProcess is None:
        if require_pty:
            raise PtyUnavailable("pywinpty installed but PtyProcess API missing")
        return _spawn_pipes(argv, cwd=cwd, env=cli_env, timeout_s=timeout_s, on_line=on_line)

    proc = PtyProcess.spawn(list(argv), cwd=cwd, env=cli_env)
    chunks: list[str] = []
    buf = ""
    timed_out = False
    deadline = time.monotonic() + max(1.0, timeout_s)
    try:
        while proc.isalive():
            if time.monotonic() > deadline:
                timed_out = True
                try:
                    proc.terminate(force=True)
                except Exception:
                    pass
                break
            try:
                data = proc.read(4096)
            except EOFError:
                break
            except Exception:
                break
            if not data:
                continue
            text = data if isinstance(data, str) else data.decode("utf-8", errors="replace")
            chunks.append(text)
            buf += text
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                if on_line:
                    on_line(line)
        if buf and on_line:
            on_line(buf)
        code = int(getattr(proc, "exitstatus", None) or getattr(proc, "returncode", 0) or 0)
        return PtyResult(returncode=code, stdout="".join(chunks), timed_out=timed_out)
    finally:
        try:
            if proc.isalive():
                proc.terminate(force=True)
        except Exception:
            pass


def _spawn_pipes(
    argv: Sequence[str],
    *,
    cwd: str | None,
    env: Mapping[str, str],
    timeout_s: float,
    on_line: Callable[[str], None] | None,
) -> PtyResult:
    proc = subprocess.Popen(
        list(argv),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=cwd,
        env=env,
        text=True,
        bufsize=1,
    )
    chunks: list[str] = []
    timed_out = False
    assert proc.stdout is not None
    stream: BinaryIO | object = proc.stdout
    deadline = time.monotonic() + max(1.0, timeout_s)
    try:
        while True:
            if time.monotonic() > deadline:
                timed_out = True
                proc.kill()
                break
            line = stream.readline()  # type: ignore[attr-defined]
            if line == "" and proc.poll() is not None:
                break
            if line:
                chunks.append(line)
                if on_line:
                    on_line(line.rstrip("\n"))
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
        raise
    return PtyResult(
        returncode=int(proc.returncode if proc.returncode is not None else -1),
        stdout="".join(chunks),
        timed_out=timed_out,
    )

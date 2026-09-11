"""Multi-signal real activity and stall detection engine.

Implements the multi-signal watchdog pattern to prevent premature timeouts
and false stall aborts in long-running or delegated agent tasks.

Principle:
A job or orchestrator process should never be considered stalled based
solely on silence in a single stream (e.g. stderr). Silence is normal
when waiting for tool results, delegating to sub-CLIs, or processing
multimodal models. Activity is observed across multiple independent signals:

1. Process I/O growth (stdout and/or stderr byte growth)
2. External progress updates (e.g. Discord progress digests, outbox state)
3. Workspace / job directory mtime changes
4. Sibling or child worker process liveness
5. Explicit lease renewal (e.g. job_extend)
"""
from __future__ import annotations

import enum
import errno
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence


class ActivitySignal(str, enum.Enum):
    NONE = "none"
    STDERR = "stderr"
    STDOUT = "stdout"
    PROGRESS = "external_progress"
    WORKSPACE_MTIME = "workspace_mtime"
    SIBLING_CLI = "sibling_cli"
    CHILD_PROCESS = "child_process"
    LEASE_RENEW = "lease_renew"


@dataclass
class ActivitySnapshot:
    """Watermarks tracking state across successive activity checks."""
    last_activity_ts: float = field(default_factory=time.time)
    last_stderr_size: int = 0
    last_stdout_size: int = 0
    last_progress_ts: float = 0.0
    last_workspace_mtime: float = 0.0
    last_signal: ActivitySignal = ActivitySignal.NONE
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ActivityReport:
    """Result of an activity evaluation at a given timestamp."""
    active: bool
    signal: ActivitySignal
    idle_seconds: float
    snapshot: ActivitySnapshot
    detail: str = ""


def is_pid_alive(pid: int) -> bool:
    """Check whether a process PID is currently alive on Linux or Windows."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError as e:
        if sys.platform != "win32" and e.errno == errno.EPERM:
            return True
        return False
    except PermissionError:
        return True


def get_dir_newest_mtime(target_dir: str | Path | None, max_depth: int = 2) -> float:
    """Recursively find the most recent file/directory mtime up to max_depth."""
    if not target_dir:
        return 0.0
    path = Path(target_dir)
    if not path.is_dir():
        return 0.0

    newest = 0.0
    try:
        newest = max(newest, float(path.stat().st_mtime))
    except Exception:
        pass

    if max_depth <= 0:
        return newest

    try:
        for entry in path.iterdir():
            try:
                newest = max(newest, float(entry.stat().st_mtime))
                if entry.is_dir() and max_depth > 1:
                    newest = max(newest, get_dir_newest_mtime(entry, max_depth=max_depth - 1))
            except (OSError, PermissionError):
                continue
    except (OSError, PermissionError):
        pass

    return newest


class RealActivityMonitor:
    """Multi-signal activity monitor for supervising worker execution."""

    def __init__(
        self,
        *,
        stall_threshold_s: float = 180.0,
        progress_freshness_s: float = 360.0,
        workspace_freshness_s: float = 360.0,
        initial_activity_ts: float | None = None,
    ) -> None:
        self.stall_threshold_s = float(stall_threshold_s)
        self.progress_freshness_s = float(progress_freshness_s)
        self.workspace_freshness_s = float(workspace_freshness_s)
        now = time.time()
        self.snapshot = ActivitySnapshot(
            last_activity_ts=float(initial_activity_ts if initial_activity_ts is not None else now)
        )

    def renew(self, now: float | None = None, reason: str = "") -> ActivityReport:
        """Explicitly renew activity (e.g. lease extension or user +30)."""
        ts = float(now if now is not None else time.time())
        self.snapshot.last_activity_ts = ts
        self.snapshot.last_signal = ActivitySignal.LEASE_RENEW
        return ActivityReport(
            active=True,
            signal=ActivitySignal.LEASE_RENEW,
            idle_seconds=0.0,
            snapshot=self.snapshot,
            detail=reason or "lease explicitly renewed",
        )

    def evaluate(
        self,
        *,
        now: float | None = None,
        stderr_size: int = 0,
        stdout_size: int = 0,
        external_progress_ts: float = 0.0,
        workspace_dir: str | Path | None = None,
        sibling_pids: Sequence[int] = (),
        child_pids: Sequence[int] = (),
        custom_checker: Callable[[], tuple[bool, ActivitySignal, str]] | None = None,
    ) -> ActivityReport:
        """Evaluate whether any real activity occurred, resetting the stall timer.

        If ANY signal is active, idle time resets to 0.0.
        Only if ALL signals remain quiet beyond stall_threshold_s is the job
        considered stalled.
        """
        t_now = float(now if now is not None else time.time())

        # 1. stderr byte growth
        if stderr_size > self.snapshot.last_stderr_size:
            self.snapshot.last_stderr_size = stderr_size
            self.snapshot.last_activity_ts = t_now
            self.snapshot.last_signal = ActivitySignal.STDERR
            return ActivityReport(
                active=True,
                signal=ActivitySignal.STDERR,
                idle_seconds=0.0,
                snapshot=self.snapshot,
                detail=f"stderr growth to {stderr_size} bytes",
            )

        # 2. stdout byte growth
        if stdout_size > self.snapshot.last_stdout_size:
            self.snapshot.last_stdout_size = stdout_size
            self.snapshot.last_activity_ts = t_now
            self.snapshot.last_signal = ActivitySignal.STDOUT
            return ActivityReport(
                active=True,
                signal=ActivitySignal.STDOUT,
                idle_seconds=0.0,
                snapshot=self.snapshot,
                detail=f"stdout growth to {stdout_size} bytes",
            )

        # 3. External progress (e.g. Discord progress digest within fresh window)
        fresh_win = max(self.stall_threshold_s, self.progress_freshness_s)
        if external_progress_ts > 0.0 and (t_now - external_progress_ts) < fresh_win:
            self.snapshot.last_progress_ts = max(self.snapshot.last_progress_ts, external_progress_ts)
            self.snapshot.last_activity_ts = t_now
            self.snapshot.last_signal = ActivitySignal.PROGRESS
            return ActivityReport(
                active=True,
                signal=ActivitySignal.PROGRESS,
                idle_seconds=0.0,
                snapshot=self.snapshot,
                detail=f"external progress fresh (age {t_now - external_progress_ts:.1f}s < {fresh_win}s)",
            )

        # 4. Workspace / job directory mtime changes
        if workspace_dir:
            newest_mtime = get_dir_newest_mtime(workspace_dir)
            ws_win = max(self.stall_threshold_s, self.workspace_freshness_s)
            if newest_mtime > self.snapshot.last_workspace_mtime and (t_now - newest_mtime) < ws_win:
                self.snapshot.last_workspace_mtime = newest_mtime
                self.snapshot.last_activity_ts = t_now
                self.snapshot.last_signal = ActivitySignal.WORKSPACE_MTIME
                return ActivityReport(
                    active=True,
                    signal=ActivitySignal.WORKSPACE_MTIME,
                    idle_seconds=0.0,
                    snapshot=self.snapshot,
                    detail=f"workspace mtime updated ({newest_mtime:.1f})",
                )

        # 5. Sibling worker CLI in same conversation/channel
        for pid in sibling_pids:
            if is_pid_alive(pid):
                self.snapshot.last_activity_ts = t_now
                self.snapshot.last_signal = ActivitySignal.SIBLING_CLI
                return ActivityReport(
                    active=True,
                    signal=ActivitySignal.SIBLING_CLI,
                    idle_seconds=0.0,
                    snapshot=self.snapshot,
                    detail=f"sibling worker alive (PID {pid})",
                )

        # 6. Child process liveness
        for cpid in child_pids:
            if is_pid_alive(cpid):
                self.snapshot.last_activity_ts = t_now
                self.snapshot.last_signal = ActivitySignal.CHILD_PROCESS
                return ActivityReport(
                    active=True,
                    signal=ActivitySignal.CHILD_PROCESS,
                    idle_seconds=0.0,
                    snapshot=self.snapshot,
                    detail=f"child process alive (PID {cpid})",
                )

        # 7. Custom checker hook (extensibility)
        if custom_checker is not None:
            active_custom, sig, detail = custom_checker()
            if active_custom:
                self.snapshot.last_activity_ts = t_now
                self.snapshot.last_signal = sig
                return ActivityReport(
                    active=True,
                    signal=sig,
                    idle_seconds=0.0,
                    snapshot=self.snapshot,
                    detail=detail,
                )

        # No activity detected
        idle_s = max(0.0, t_now - self.snapshot.last_activity_ts)
        is_stalled = idle_s >= self.stall_threshold_s

        return ActivityReport(
            active=not is_stalled,
            signal=ActivitySignal.NONE,
            idle_seconds=idle_s,
            snapshot=self.snapshot,
            detail=f"idle for {idle_s:.1f}s (stall threshold {self.stall_threshold_s:.1f}s)",
        )


def real_activity_seen(
    *,
    now: float,
    stall_s: float,
    last_activity: float,
    stderr_size: int,
    last_stderr_size: int,
    stdout_size: int | None = None,
    last_stdout_size: int | None = None,
    progress_ts: float = 0.0,
    workspace_dir: str | Path | None = None,
    last_workspace_mtime: float = 0.0,
    sibling_alive: bool = False,
    progress_fresh_s: float = 360.0,
) -> tuple[bool, dict[str, Any]]:
    """Functional helper compatible with FE-BOT / pack interface.

    Returns:
        (active, metadata_dict)
    """
    meta: dict[str, Any] = {
        "last_stderr_size": last_stderr_size,
        "last_stdout_size": last_stdout_size if last_stdout_size is not None else 0,
        "last_progress_ts": progress_ts,
        "last_workspace_mtime": last_workspace_mtime,
        "signal": ActivitySignal.NONE.value,
    }

    if stderr_size > last_stderr_size:
        meta["last_stderr_size"] = stderr_size
        meta["signal"] = ActivitySignal.STDERR.value
        return True, meta

    if stdout_size is not None and last_stdout_size is not None and stdout_size > last_stdout_size:
        meta["last_stdout_size"] = stdout_size
        meta["signal"] = ActivitySignal.STDOUT.value
        return True, meta

    fresh_s = max(float(stall_s), float(progress_fresh_s))
    if progress_ts > 0.0 and (now - progress_ts) < fresh_s:
        meta["signal"] = ActivitySignal.PROGRESS.value
        return True, meta

    if workspace_dir:
        newest = get_dir_newest_mtime(workspace_dir)
        if newest > 0.0 and (now - newest) < fresh_s:
            meta["last_workspace_mtime"] = max(last_workspace_mtime, newest)
            meta["signal"] = ActivitySignal.WORKSPACE_MTIME.value
            return True, meta

    if sibling_alive:
        meta["signal"] = ActivitySignal.SIBLING_CLI.value
        return True, meta

    idle_s = now - float(last_activity)
    meta["idle_s"] = idle_s
    return False, meta

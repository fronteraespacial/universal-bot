"""Per-job live trail: one embed, edited in place, with isolated marker files.

Marker and event files are keyed by ``(channel_id, job_id)`` so two jobs in
the same channel never share steps. Tool lines are appended by any process
via :func:`push_event` and folded in on :meth:`LiveTrail.poll_events`,
dropping a line that repeats the previous step.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from universal_bot.unified_progress.cli_logs import dur_text, message_link, post_job_log
from universal_bot.unified_progress.config import FAIL_COLOR, UnifiedProgressConfig, stop_button_enabled
from universal_bot.unified_progress.stop_control import (
    CANCEL_COLOR,
    INACTIVE_COLOR,
    IS_COMPONENTS_V2,
    embed_markdown,
    is_manual_cancel,
    progress_card,
    running_stop_components,
)
from universal_bot.unified_progress.transport import DiscordTransport, retry_on_rate_limit

log = logging.getLogger("universal_bot.unified_progress.trail")

DEFAULT_COLOR = 0x5865F2
MARK_TTL_S = 4 * 3600
STEP_MAX = 300
EMBED_FALLBACK_MAX = 3900

_SECRET_RES = [
    re.compile(r"(?i)\b(bearer|bot)\s+[a-z0-9._\-]{20,}"),
    re.compile(r"(?i)\b(token|secret|password|passwd|api[_-]?key|authorization)\s*[=:]\s*\S+"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\b[MN][A-Za-z\d]{23,}\.[\w-]{6}\.[\w-]{27,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\b[a-f0-9]{40,}\b"),
]
_ABS_PATH_RE = re.compile(r"(?<![\w.])/(?:[\w.@+\-]+/)*[\w.@+\-]+")
_HINT_KEYS = ("query", "q", "url", "username", "action", "title", "path", "name", "topic")


def sanitize(text: str, *, limit: int = 80, scratch: str | None = None, nonadmin: bool = False) -> str:
    cleaned = " ".join(str(text or "").split())
    for pattern in _SECRET_RES:
        cleaned = pattern.sub("[hidden]", cleaned)
    if scratch:
        root = str(scratch).rstrip("/")
        cleaned = cleaned.replace(root + "/", "./").replace(root, ".")
    if nonadmin:
        cleaned = _ABS_PATH_RE.sub(lambda match: "…/" + match.group(0).rsplit("/", 1)[-1], cleaned)
    cleaned = cleaned.replace("`", "ˋ").replace("@", "@\u200b")
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 1].rstrip() + "…"
    return cleaned


def format_tool_line(
    name: str,
    args: Mapping[str, Any] | None = None,
    *,
    scratch: str | None = None,
    nonadmin: bool = False,
) -> str | None:
    """One trail line for a tool call. Empty names are ignored."""
    tool = str(name or "").strip()
    if not tool:
        return None
    inner = dict(args or {})
    nested = inner.get("args")
    if isinstance(nested, dict):
        inner = nested
    hint = ""
    for key in _HINT_KEYS:
        if inner.get(key):
            hint = f': “{sanitize(str(inner[key]), scratch=scratch, nonadmin=nonadmin)}”'
            break
    return f"🔧 {sanitize(tool, limit=60, scratch=scratch, nonadmin=nonadmin)}{hint}"


def digest_line(content: str) -> str:
    """Collapse a multi-line digest into a single pin line."""
    text = str(content or "")
    text = re.sub(r"`[^`\n]*`", "", text)
    text = text.replace("**", "")
    parts = [part.strip(" ·") for part in text.splitlines() if part.strip(" ·")]
    one = " ".join(" · ".join(parts).split())
    return f"📌 {one[:280]}" if one else ""


def _safe_id(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(value or ""))


def job_key(channel_id: Any, job_id: Any) -> str:
    return f"{_safe_id(channel_id)}__{_safe_id(job_id)}"


def marker_path(state_dir: Path | str, channel_id: Any, job_id: Any) -> Path:
    return Path(state_dir) / "live_trail" / f"{job_key(channel_id, job_id)}.json"


def events_path(state_dir: Path | str, channel_id: Any, job_id: Any) -> Path:
    return Path(state_dir) / "live_trail" / f"{job_key(channel_id, job_id)}.events.jsonl"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def read_marker(
    state_dir: Path | str,
    channel_id: Any,
    job_id: Any,
    *,
    now: float | None = None,
    ttl_s: float = MARK_TTL_S,
    require_alive: bool = True,
) -> dict[str, Any] | None:
    """Live marker for this job, or ``None`` when missing, stale, or ownerless.

    ``require_alive`` drops the file when the owner pid is gone. The stop
    button handler turns this off so admins can still read ``author_id``.
    """
    path = marker_path(state_dir, channel_id, job_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    stamp = float(data.get("ts") or 0)
    if (now if now is not None else time.time()) - stamp > ttl_s:
        return None
    if require_alive and not _pid_alive(int(data.get("pid") or 0)):
        return None
    return data


def write_marker(
    state_dir: Path | str,
    channel_id: Any,
    job_id: Any,
    message_id: str,
    *,
    ingest: bool = True,
    author_id: str | None = None,
    components_v2: bool = False,
    now: float | None = None,
) -> None:
    payload = {
        "pid": os.getpid(),
        "ts": now if now is not None else time.time(),
        "message_id": str(message_id),
        "ingest": bool(ingest),
        "channel_id": str(channel_id),
        "job_id": str(job_id),
        "author_id": str(author_id or "").strip(),
        "components_v2": bool(components_v2),
    }
    _atomic_write(marker_path(state_dir, channel_id, job_id), json.dumps(payload))


def clear_job_files(state_dir: Path | str, channel_id: Any, job_id: Any) -> None:
    for path in (
        marker_path(state_dir, channel_id, job_id),
        events_path(state_dir, channel_id, job_id),
    ):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            log.exception("trail cleanup failed path=%s", path)


def push_event(
    state_dir: Path | str,
    channel_id: Any,
    job_id: Any,
    line: str,
    *,
    now: float | None = None,
) -> bool:
    """Append a step for one job. Refuses when that job has no ingesting marker."""
    text = (line or "").strip()
    if not text:
        return False
    marker = read_marker(state_dir, channel_id, job_id, now=now)
    if not marker or not marker.get("ingest"):
        return False
    path = events_path(state_dir, channel_id, job_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"ts": now if now is not None else time.time(), "line": text}) + "\n")
        return True
    except OSError:
        log.exception("trail push_event failed")
        return False


class Trail:
    """Step list for one job. Consecutive identical lines collapse to one."""

    def __init__(self, label: str, *, now: Callable[[], float] | None = None) -> None:
        self.label = label
        self._now = now or time.time
        self.started = float(self._now())
        self.ended: float | None = None
        self.steps: list[str] = []
        self.state = "running"
        self.note = ""
        self.last_pin = ""

    def add(self, line: str) -> bool:
        text = (line or "").strip()
        if not text:
            return False
        if self.steps and self.steps[-1] == text:
            return False
        self.steps.append(text)
        if text.startswith("📌 "):
            self.last_pin = text
        return True

    def finish(self, ok: bool, note: str = "") -> None:
        self.state = "done" if ok else "failed"
        self.note = note
        self.ended = float(self._now())

    def elapsed(self) -> float:
        end = self.ended if self.ended is not None else float(self._now())
        return end - self.started


def _clip(text: str, limit: int = STEP_MAX) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def clock_text(seconds: float) -> str:
    whole = int(max(0, seconds))
    return f"{whole // 60}:{whole % 60:02d}"


def render_live_embed(trail: Trail, *, display_name: str, color: int) -> dict[str, Any]:
    """Running embed: current step, and the last pin when it is not that step."""
    current = trail.steps[-1] if trail.steps else "💭 starting…"
    current = _clip(current)
    description = current
    if trail.last_pin and trail.last_pin != (trail.steps[-1] if trail.steps else ""):
        description = f"{current}\n-# {_clip(trail.last_pin)}"
    n = max(1, len(trail.steps))
    return {
        "title": f"⏳ {display_name} working… {clock_text(trail.elapsed())}",
        "description": description,
        "footer": {"text": f"step {n} · {trail.label}"},
        "color": color,
    }


def render_collapsed_embed(
    trail: Trail,
    log_link: str | None,
    *,
    color: int,
    fail_color: int = FAIL_COLOR,
) -> dict[str, Any]:
    """Finished embed. Without a log link the step list stays in the description."""
    ok = trail.state == "done"
    elapsed = dur_text(trail.elapsed())
    n = len(trail.steps)
    step_word = "step" if n == 1 else "steps"
    if ok:
        parts = [f"✅ Done in {elapsed}", f"{n} {step_word}"]
    elif is_manual_cancel(trail.note):
        parts = [f"🛑 {trail.note or 'Cancelado manualmente.'} · {elapsed}", f"{n} {step_word}"]
    else:
        parts = [f"⚠️ {trail.note or 'ended with error'} · {elapsed}", f"{n} {step_word}"]
    if log_link:
        parts.append(f"[full trail]({log_link})")
    description = " · ".join(parts)
    if not log_link and trail.steps:
        lines = [f"· {line}" for line in trail.steps]
        body = "\n".join(lines)
        while len(description) + 1 + len(body) > EMBED_FALLBACK_MAX and len(lines) > 1:
            lines = lines[1:]
            body = "\n".join(["· …"] + lines)
        description = f"{description}\n{body}"[:EMBED_FALLBACK_MAX]
    finish_color = color if ok else fail_color
    if not ok and is_manual_cancel(trail.note):
        finish_color = CANCEL_COLOR
    return {
        "description": description,
        "footer": {"text": trail.label},
        "color": finish_color,
    }


class _Throttle:
    def __init__(self, min_s: float, now: Callable[[], float]) -> None:
        self.min_s = min_s
        self._now = now
        self.last = -1e9

    def ready(self) -> bool:
        return (self._now() - self.last) >= self.min_s

    def mark(self) -> None:
        self.last = self._now()


class LiveTrail:
    """One Discord message per job. Later steps edit that message."""

    def __init__(
        self,
        cfg: UnifiedProgressConfig,
        transport: DiscordTransport,
        channel_id: str,
        job_id: str,
        label: str,
        *,
        color: int | None = None,
        reply_to: str | None = None,
        meta: Mapping[str, Any] | None = None,
        now: Callable[[], float] | None = None,
        mono: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
        ingest: bool = True,
    ) -> None:
        self.cfg = cfg
        self.transport = transport
        self.channel_id = str(channel_id)
        self.job_id = str(job_id)
        self.color = DEFAULT_COLOR if color is None else color
        self.reply_to = reply_to
        self.meta = dict(meta or {})
        self.meta.setdefault("job_id", self.job_id)
        self.meta.setdefault("channel_id", self.channel_id)
        self.ingest = ingest
        self._now = now or time.time
        self._sleep = sleep or time.sleep
        self.trail = Trail(label, now=self._now)
        self.throttle = _Throttle(cfg.min_edit_s, mono or time.monotonic)
        self.message_id: str | None = None
        self.log_message_id: str | None = None
        self._last_sent: dict[str, Any] | None = None
        self._dirty = False
        self._ev_off = 0
        self.edits = 0
        self._components_v2 = False

    def _call(self, fn: Callable[[], Any]) -> Any:
        return retry_on_rate_limit(fn, retries=self.cfg.rate_limit_retries, sleep=self._sleep)

    def _stop_on(self) -> bool:
        return stop_button_enabled(self.cfg)

    def _live_action_row(self) -> dict[str, Any] | None:
        if not self._stop_on() or self.trail.state != "running":
            return None
        rows = running_stop_components(self.channel_id, self.job_id)
        return rows[0] if rows else None

    def _v2_components(self, embed: dict[str, Any], *, include_button: bool) -> list[dict[str, Any]]:
        row = self._live_action_row() if include_button else None
        accent = int(embed.get("color") or self.color)
        return progress_card(embed_markdown(embed), accent=accent, action_row=row)

    def _post_body(self, embed: dict[str, Any], *, include_button: bool) -> dict[str, Any]:
        if self._stop_on() and self.trail.state == "running":
            row = self._live_action_row()
            if row is not None:
                self._components_v2 = True
                return {
                    "content": "",
                    "embeds": None,
                    "components": self._v2_components(embed, include_button=True),
                    "flags": IS_COMPONENTS_V2,
                }
        return {"content": "", "embeds": [embed], "components": None, "flags": None}

    def _edit_body(self, embed: dict[str, Any], *, include_button: bool) -> dict[str, Any]:
        if self._components_v2:
            if not include_button and self._stop_on():
                accent = INACTIVE_COLOR
                if is_manual_cancel(self.trail.note):
                    accent = CANCEL_COLOR
                elif self.trail.state == "done":
                    accent = int(embed.get("color") or self.color)
                elif self.trail.state == "failed" and not is_manual_cancel(self.trail.note):
                    accent = FAIL_COLOR
                return {
                    "content": "",
                    "embeds": None,
                    "components": progress_card(embed_markdown(embed), accent=accent, action_row=None),
                    "flags": IS_COMPONENTS_V2,
                }
            return {
                "content": "",
                "embeds": None,
                "components": self._v2_components(embed, include_button=include_button),
                "flags": IS_COMPONENTS_V2,
            }
        return {"content": None, "embeds": [embed], "components": None, "flags": None}

    def render(self) -> dict[str, Any]:
        if self.trail.state == "running":
            return render_live_embed(
                self.trail, display_name=self.cfg.display_name, color=self.color
            )
        return render_collapsed_embed(self.trail, None, color=self.color)

    def start(self) -> LiveTrail:
        embed = self.render()
        body = self._post_body(embed, include_button=True)

        def _send() -> str:
            return str(
                self.transport.send(
                    self.channel_id,
                    content=body.get("content") or "",
                    embeds=body.get("embeds"),
                    components=body.get("components"),
                    flags=body.get("flags"),
                    reply_to=self.reply_to,
                )
                or ""
            )

        try:
            message_id = self._call(_send)
        except Exception:
            log.exception("live trail post failed channel=%s job=%s", self.channel_id, self.job_id)
            message_id = ""
        self.throttle.mark()
        if message_id:
            self.message_id = message_id
            self._last_sent = embed
            if self.ingest:
                write_marker(
                    self.cfg.state_dir,
                    self.channel_id,
                    self.job_id,
                    message_id,
                    ingest=True,
                    author_id=str(self.meta.get("author_id") or ""),
                    components_v2=self._components_v2,
                )
        return self

    def add_step(self, line: str) -> bool:
        if not self.trail.add(line):
            return False
        self._dirty = True
        if self.message_id and self.throttle.ready():
            self.flush()
        return True

    def poll_events(self) -> None:
        """Fold new event-file lines into this job only."""
        if not self.ingest:
            return
        path = events_path(self.cfg.state_dir, self.channel_id, self.job_id)
        try:
            with path.open("rb") as handle:
                handle.seek(self._ev_off)
                data = handle.read()
        except OSError:
            return
        if not data:
            return
        cut = data.rfind(b"\n")
        if cut < 0:
            return
        self._ev_off += cut + 1
        for raw in data[: cut + 1].decode("utf-8", "replace").splitlines():
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            self.add_step(str(payload.get("line") or ""))

    def flush(self) -> None:
        if not self.message_id:
            return
        embed = self.render()
        self._dirty = False
        if embed == self._last_sent and self.trail.state == "running":
            return
        body = self._edit_body(embed, include_button=self.trail.state == "running")

        def _edit() -> None:
            self.transport.edit(
                self.channel_id,
                self.message_id or "",
                content=body.get("content"),
                embeds=body.get("embeds"),
                components=body.get("components"),
                flags=body.get("flags"),
            )

        try:
            self._call(_edit)
        except Exception:
            log.exception("live trail edit failed channel=%s job=%s", self.channel_id, self.job_id)
            return
        self._last_sent = embed
        self.edits += 1
        self.throttle.mark()

    def finish(
        self,
        ok: bool,
        note: str = "",
        quota_block: str = "",
        *,
        channel_name: str | None = None,
    ) -> None:
        """Close the job: optional logs embed, then edit the live message down."""
        self.poll_events()
        self.trail.finish(ok, note)
        log_link = None
        if self.cfg.cli_logs_channel_id:
            self.log_message_id = post_job_log(
                self.cfg,
                self.transport,
                self.trail,
                self.meta,
                quota_block,
                channel_name=channel_name,
                sleep=self._sleep,
                now=float(self._now()),
            )
            guild = str(self.meta.get("guild_id") or "")
            if self.log_message_id and guild:
                log_link = message_link(guild, self.cfg.cli_logs_channel_id, self.log_message_id)
        collapsed = render_collapsed_embed(self.trail, log_link, color=self.color)
        if self.message_id:
            body = self._edit_body(collapsed, include_button=False)

            def _edit() -> None:
                self.transport.edit(
                    self.channel_id,
                    self.message_id or "",
                    content=body.get("content"),
                    embeds=body.get("embeds"),
                    components=body.get("components"),
                    flags=body.get("flags"),
                )

            try:
                self._call(_edit)
                self._last_sent = collapsed
                self.edits += 1
            except Exception:
                log.exception("live trail collapse failed channel=%s job=%s", self.channel_id, self.job_id)
        marker = read_marker(self.cfg.state_dir, self.channel_id, self.job_id)
        owns_marker = marker is None or str(marker.get("message_id") or "") == str(self.message_id or "")
        if owns_marker:
            clear_job_files(self.cfg.state_dir, self.channel_id, self.job_id)

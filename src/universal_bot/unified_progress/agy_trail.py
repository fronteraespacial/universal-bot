"""Map AGY ``--output-format stream-json`` events into unified live-trail steps.

AGY print mode defaults to plain text. Native tools (``run_command``, file
reads, search) never reach ``announce_tool``, so the progress card stays at
0 steps unless the model happens to call an MCP tool or ``discord_progress``.
Headless NDJSON (event: init / step_update / result) allows mapping tool
invocations directly into live progress steps while extracting the final
clean markdown response from result.response.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger("universal_bot.unified_progress.agy_trail")

_SKIP_TOOLS = {"ask_permission", "discord_progress"}

ICON = {
    "shell": "💻",
    "read": "📄",
    "edit": "✍️",
    "grep": "🔎",
    "ls": "📂",
    "web": "🌐",
    "other": "⚙️",
    "think": "💭",
    "answer": "✍️",
}


def sanitize(text: str, limit: int = 80) -> str:
    cleaned = " ".join(str(text or "").split()).replace("`", "ˋ")
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 1].rstrip() + "…"
    return cleaned


def push_line(
    line: str,
    *,
    channel: str | None = None,
    job: str | None = None,
    state_dir: str | Path | None = None,
) -> bool:
    line = (line or "").strip()
    chan = (
        channel
        or os.environ.get("FE_UNIFIED_TRAIL_CHANNEL")
        or os.environ.get("UB_TRAIL_CHANNEL")
        or ""
    ).strip()
    if not line or not chan:
        return False
    jid = (
        job
        or os.environ.get("FE_UNIFIED_TRAIL_JOB")
        or os.environ.get("UB_TRAIL_JOB")
        or os.environ.get("FE_DISCORD_MESSAGE_ID")
        or ""
    ).strip()

    # 1. If explicit state_dir passed, prioritize unified_progress trail
    if state_dir:
        try:
            from universal_bot.unified_progress.trail import push_event

            if push_event(state_dir, chan, jid or "default", line):
                return True
        except Exception:
            pass

    # 2. Try host live trail if present
    try:
        import cursor_live_trail as clt

        if clt.push_event(chan, line, job=jid or None):
            return True
    except Exception:
        pass

    # 3. Try unified_card absorb
    try:
        import unified_card as uc

        res = uc.absorb(chan, line, reply_to=jid or None)
        if res and res.get("absorbed"):
            return True
    except Exception:
        pass

    # 4. Fall back to unified_progress trail with env or default dir
    try:
        from universal_bot.unified_progress.trail import push_event

        sdir = state_dir or os.environ.get("UB_STATE_DIR") or "/tmp"
        if push_event(sdir, chan, jid or "default", line):
            return True
    except Exception:
        pass

    return False


def _params(step: dict[str, Any]) -> dict[str, Any]:
    info = step.get("tool_info") if isinstance(step.get("tool_info"), dict) else {}
    raw = info.get("parameters") if isinstance(info.get("parameters"), dict) else {}
    if not raw and isinstance(step.get("parameters"), dict):
        raw = step["parameters"]
    return {str(k).lower(): v for k, v in raw.items()}


def _pick(params: dict[str, Any], *names: str) -> str:
    for name in names:
        val = params.get(name)
        if val is None:
            continue
        text = str(val).strip()
        if text:
            return text
    return ""


def line_for_step(
    step: dict[str, Any],
    *,
    seen_idx: set[Any],
    thought: bool,
    drafted: bool,
    saw_tool: bool,
) -> tuple[str | None, bool, bool, bool]:
    """Return (trail line, thought, drafted, saw_tool). Pure. One line per step index."""
    kind = str(step.get("step_type") or "").lower()
    idx = step.get("step_index")
    if kind in ("user_input", "checkpoint", ""):
        return None, thought, drafted, saw_tool
    if kind == "tool":
        if idx in seen_idx:
            return None, thought, drafted, saw_tool
        name = str(step.get("tool_name") or "").strip()
        info = step.get("tool_info") if isinstance(step.get("tool_info"), dict) else {}
        if not name:
            name = str(info.get("name") or "tool")
        low = name.lower()
        if low in _SKIP_TOOLS:
            seen_idx.add(idx)
            return None, thought, drafted, True
        params = _params(step)
        state = str(step.get("state") or "").upper()
        hint = _pick(
            params,
            "commandline",
            "command",
            "cmd",
            "path",
            "targetfile",
            "target_file",
            "file",
            "filename",
            "query",
            "pattern",
            "searchterm",
            "url",
        )
        if state not in ("DONE", "") and not hint and not name:
            return None, thought, drafted, saw_tool
        seen_idx.add(idx)
        s = sanitize(hint, limit=60) if hint else ""
        if low in ("run_command", "shell", "bash", "command", "terminal"):
            line = f"{ICON['shell']} `{s or 'shell'}`"
        elif low in ("view_file", "read_file", "read", "cat"):
            line = f"{ICON['read']} leyendo {s or 'archivo'}"
        elif low in ("write_to_file", "write", "search_replace", "replace", "edit", "edit_file"):
            line = f"{ICON['edit']} editando {s or 'archivo'}"
        elif low in ("grep", "search", "search_in_file", "codebase_search", "find", "glob"):
            line = f"{ICON['grep']} buscando “{s}”" if s else f"{ICON['grep']} buscando"
        elif low in ("list_dir", "ls", "listdir"):
            line = f"{ICON['ls']} listando {s or '.'}"
        elif any(k in low for k in ("web", "fetch", "browser", "search")):
            line = f"{ICON['web']} {s}" if s else f"{ICON['web']} web"
        else:
            shown = sanitize(name, limit=40)
            line = f"{ICON['other']} {shown}" + (f": “{s}”" if s else "")
        return line, thought, drafted, True
    sub = step.get("subagent_info") if isinstance(step.get("subagent_info"), dict) else None
    if sub and idx not in seen_idx:
        seen_idx.add(idx)
        name = sanitize(str(sub.get("name") or sub.get("agent") or "subagente"), limit=40)
        task = sanitize(str(sub.get("task") or sub.get("prompt") or ""), limit=50)
        line = f"{ICON['other']} subagente {name}" + (f": “{task}”" if task else "")
        return line, thought, drafted, saw_tool
    if kind in ("agent_response", "thinking", "thought") or "think" in kind:
        if saw_tool and not drafted and str(step.get("text_delta") or "").strip():
            return f"{ICON['answer']} redactando respuesta", thought, True, saw_tool
        if not thought and not saw_tool:
            return f"{ICON['think']} analizando el pedido", True, drafted, saw_tool
    return None, thought, drafted, saw_tool


def parse_event(ev: dict[str, Any]) -> tuple[dict[str, Any] | None, str, str]:
    """Return (step or None, response, status). ``response`` set only on result."""
    kind = str(ev.get("event") or ev.get("type") or "")
    if kind == "step_update" and isinstance(ev.get("step_update"), dict):
        return ev["step_update"], "", ""
    if kind == "result":
        res = ev.get("result") if isinstance(ev.get("result"), dict) else ev
        return None, str(res.get("response") or ""), str(res.get("status") or "")
    if "response" in ev and "status" in ev and "event" not in ev:
        return None, str(ev.get("response") or ""), str(ev.get("status") or "")
    return None, "", ""


class AgyStream:
    """Accumulate the final answer and push one trail line per tool step."""

    def __init__(self, *, state_dir: str | Path | None = None) -> None:
        self.response = ""
        self.status = ""
        self.saw_event = False
        self._seen: set[Any] = set()
        self._thought = False
        self._drafted = False
        self._saw_tool = False
        self.deltas: list[str] = []
        self.state_dir = state_dir

    def consume(self, raw: str, *, channel: str | None = None, job: str | None = None) -> None:
        raw = (raw or "").strip()
        if not raw.startswith("{"):
            return
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError:
            return
        if not isinstance(ev, dict):
            return
        self.saw_event = True
        step, response, status = parse_event(ev)
        if response or status:
            if response:
                self.response = response
            if status:
                self.status = status
        if not step:
            return
        if str(step.get("step_type") or "").lower() == "agent_response":
            delta = str(step.get("text_delta") or "")
            if delta:
                self.deltas.append(delta)
        line, self._thought, self._drafted, self._saw_tool = line_for_step(
            step,
            seen_idx=self._seen,
            thought=self._thought,
            drafted=self._drafted,
            saw_tool=self._saw_tool,
        )
        if line:
            push_line(line, channel=channel, job=job, state_dir=self.state_dir)


_KEPT_PREFIXES = (
    "Falló ",
    "Se cortó",
    "Se me cortó",
    "AGY error",
    "Claude error",
    "AGY no ",
    "Claude no ",
)


def public_text(stream: AgyStream, raw: str) -> str:
    """Discord reply body. Keeps wrapper errors. Prefers ``result.response``."""
    blob = str(raw or "").strip()
    if blob.startswith(_KEPT_PREFIXES):
        return blob
    if not stream.saw_event and blob.startswith("{"):
        for line in blob.splitlines():
            stream.consume(line)
    text = (stream.response or "").strip() or "".join(stream.deltas).strip()
    if text:
        return text
    if stream.saw_event:
        return "AGY no devolvió texto."
    return blob

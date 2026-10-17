"""Unified stream parsers for Cursor, OpenCode, Codex, and Grok Build CLI.

Separates intermediate pre-tool reflections/findings (pushed one at a time as
``💭 <texto>`` steps on the live progress card when tools start) from the final
post-tool answer so intermediate narration is never glued to the final reply.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from universal_bot.unified_progress.agy_trail import (
    ICON,
    push_line,
    sanitize,
    strip_live_progress_preamble,
)


def _strip_intermediate_prefixes(text: str, segments: list[str]) -> str:
    cleaned = str(text or "")
    for seg in segments:
        s = seg.strip()
        if not s:
            continue
        if cleaned.startswith(seg):
            cleaned = cleaned[len(seg) :].lstrip()
        elif cleaned.lstrip().startswith(s):
            idx = cleaned.find(s)
            if idx != -1:
                cleaned = cleaned[idx + len(s) :].lstrip()
    return cleaned.strip()


class CursorStream:
    """Parse ``cursor-agent --output-format stream-json`` events."""

    def __init__(self, *, state_dir: str | Path | None = None) -> None:
        self.state_dir = state_dir
        self.saw_event = False
        self.got_result = False
        self.is_error = False
        self.result_text = ""
        self.usage: dict[str, Any] | None = None
        self.segment_texts: list[str] = []
        self.intermediate_segments: list[str] = []
        self.all_assistant_texts: list[str] = []
        self.thinking_chunks: list[str] = []
        self.other_lines: list[str] = []
        self._phase = ""

    def _flush_intermediate(self, *, channel: str | None = None, job: str | None = None) -> None:
        if not self.segment_texts:
            return
        seg = "".join(self.segment_texts)
        self.segment_texts.clear()
        clean = seg.strip()
        if clean:
            self.intermediate_segments.append(seg)
            push_line(
                f"{ICON['think']} {sanitize(clean, limit=140)}",
                channel=channel,
                job=job,
                state_dir=self.state_dir,
            )

    def consume(
        self,
        raw: str,
        *,
        channel: str | None = None,
        job: str | None = None,
        emit_trail: bool = True,
    ) -> None:
        st = (raw or "").strip()
        if not st:
            return
        if not st.startswith("{"):
            self.other_lines.append(st)
            return
        try:
            d = json.loads(st)
        except json.JSONDecodeError:
            return
        if not isinstance(d, dict):
            return
        self.saw_event = True
        t = str(d.get("type") or "")
        sub = str(d.get("subtype") or "")
        if t == "thinking":
            txt = str(d.get("text") or "")
            if txt:
                self.thinking_chunks.append(txt)
            if sub == "completed":
                full_think = "".join(self.thinking_chunks).strip()
                self.thinking_chunks.clear()
                if full_think and emit_trail:
                    push_line(f"{ICON['think']} {sanitize(full_think, limit=140)}", channel=channel, job=job, state_dir=self.state_dir)
                elif self._phase == "" and emit_trail:
                    self._phase = "think"
                    push_line(f"{ICON['think']} analizando el pedido", channel=channel, job=job, state_dir=self.state_dir)
            elif self._phase == "" and emit_trail:
                self._phase = "think"
                push_line(f"{ICON['think']} analizando el pedido", channel=channel, job=job, state_dir=self.state_dir)
            return
        if t == "assistant":
            chunk = ""
            for c in ((d.get("message") or {}).get("content") or []):
                if isinstance(c, dict) and c.get("type") == "text":
                    chunk += str(c.get("text") or "")
            if chunk:
                self.all_assistant_texts.append(chunk)
                self.segment_texts.append(chunk)
            if self._phase == "tools":
                self._phase = "answer"
                if emit_trail:
                    push_line(f"{ICON['answer']} redactando respuesta", channel=channel, job=job, state_dir=self.state_dir)
            return
        if t == "tool_call":
            if sub == "started":
                if emit_trail:
                    self._flush_intermediate(channel=channel, job=job)
                else:
                    if self.segment_texts:
                        seg = "".join(self.segment_texts)
                        self.segment_texts.clear()
                        if seg.strip():
                            self.intermediate_segments.append(seg)
                self._phase = "tools"
                if emit_trail:
                    tc = d.get("tool_call") if isinstance(d.get("tool_call"), dict) else {}
                    for key, body in tc.items():
                        if not isinstance(body, dict):
                            continue
                        args = body.get("args") if isinstance(body.get("args"), dict) else {}
                        if key == "shellToolCall":
                            cmd = sanitize(str(args.get("command") or "shell"), limit=60)
                            push_line(f"{ICON['shell']} `{cmd}`", channel=channel, job=job, state_dir=self.state_dir)
                        elif key == "readToolCall":
                            p = sanitize(str(args.get("path") or "archivo"), limit=60)
                            push_line(f"{ICON['read']} leyendo {p}", channel=channel, job=job, state_dir=self.state_dir)
                        elif key == "editToolCall":
                            p = sanitize(str(args.get("path") or "archivo"), limit=60)
                            push_line(f"{ICON['edit']} editando {p}", channel=channel, job=job, state_dir=self.state_dir)
                        elif key == "grepToolCall":
                            pat = sanitize(str(args.get("pattern") or ""), limit=60)
                            push_line(f"{ICON['grep']} buscando “{pat}”", channel=channel, job=job, state_dir=self.state_dir)
                        elif key == "mcpToolCall":
                            tname = str(args.get("toolName") or args.get("name") or "mcp")
                            if tname not in ("getMcpToolsToolCall", "discord_progress"):
                                push_line(f"🔧 {sanitize(tname, limit=50)}", channel=channel, job=job, state_dir=self.state_dir)
            return
        if t == "result":
            self.got_result = True
            self.is_error = bool(d.get("is_error"))
            self.result_text = str(d.get("result") or "")
            if isinstance(d.get("usage"), dict):
                self.usage = d["usage"]

    def final_text(self) -> str:
        post_tool = "".join(self.segment_texts).strip()
        if self.intermediate_segments and post_tool and not self.is_error:
            return strip_live_progress_preamble(post_tool)
        res = self.result_text.strip()
        if self.intermediate_segments and res and not self.is_error:
            stripped = _strip_intermediate_prefixes(res, self.intermediate_segments)
            if stripped:
                return strip_live_progress_preamble(stripped)
        if res:
            return strip_live_progress_preamble(res)
        if post_tool:
            return strip_live_progress_preamble(post_tool)
        return strip_live_progress_preamble("".join(self.all_assistant_texts).strip())


class OpenCodeStream:
    """Parse ``opencode run --format json`` events."""

    def __init__(self, *, state_dir: str | Path | None = None) -> None:
        self.state_dir = state_dir
        self.saw_event = False
        self.seen_step = False
        self.segment_texts: list[str] = []
        self.intermediate_segments: list[str] = []
        self.all_texts: list[str] = []
        self.errors: list[str] = []

    def _flush_intermediate(self, *, channel: str | None = None, job: str | None = None, emit_trail: bool = True) -> None:
        if not self.segment_texts:
            return
        seg = "".join(self.segment_texts)
        self.segment_texts.clear()
        clean = seg.strip()
        if clean:
            self.intermediate_segments.append(seg)
            if emit_trail:
                push_line(
                    f"{ICON['think']} {sanitize(clean, limit=140)}",
                    channel=channel,
                    job=job,
                    state_dir=self.state_dir,
                )

    def consume(
        self,
        raw: str,
        *,
        channel: str | None = None,
        job: str | None = None,
        emit_trail: bool = True,
    ) -> None:
        st = (raw or "").strip()
        if not st.startswith("{"):
            return
        try:
            ev = json.loads(st)
        except json.JSONDecodeError:
            return
        if not isinstance(ev, dict):
            return
        self.saw_event = True
        t = str(ev.get("type") or "")
        part = ev.get("part") if isinstance(ev.get("part"), dict) else {}
        if t == "step_start" and not self.seen_step:
            self.seen_step = True
            if emit_trail:
                push_line(f"{ICON['think']} analizando el pedido", channel=channel, job=job, state_dir=self.state_dir)
            return
        if t == "text":
            chunk = str(part.get("text") or "")
            if chunk:
                self.all_texts.append(chunk)
                self.segment_texts.append(chunk)
            return
        if t == "tool_use":
            self._flush_intermediate(channel=channel, job=job, emit_trail=emit_trail)
            if emit_trail:
                body = part if part.get("type") == "tool" else {}
                tool = str(body.get("tool") or "tool")
                state = body.get("state") if isinstance(body.get("state"), dict) else {}
                inp = state.get("input") if isinstance(state.get("input"), dict) else {}
                title = str(state.get("title") or "").strip()
                if tool == "bash":
                    cmd = sanitize(str(inp.get("command") or title or "shell"), limit=60)
                    push_line(f"{ICON['shell']} `{cmd}`", channel=channel, job=job, state_dir=self.state_dir)
                else:
                    hint = title or str(inp.get("query") or inp.get("path") or inp.get("filePath") or inp.get("url") or "")
                    hint = sanitize(hint, limit=50) if hint else ""
                    push_line(f"🔧 {tool}" + (f": “{hint}”" if hint else ""), channel=channel, job=job, state_dir=self.state_dir)
            return
        if t == "error":
            err_data = ev.get("error") if isinstance(ev.get("error"), dict) else {}
            msg = str(
                (err_data.get("data") if isinstance(err_data.get("data"), dict) else {}).get("message")
                or err_data.get("message")
                or err_data.get("name")
                or "error"
            )
            self.errors.append(msg)

    def final_text(self) -> str:
        post_tool = "".join(self.segment_texts).strip()
        if post_tool:
            return strip_live_progress_preamble(post_tool)
        return strip_live_progress_preamble("".join(self.all_texts).strip())


class GrokCliStream:
    """Parse ``grok --output-format streaming-json`` ACP NDJSON events."""

    def __init__(self, *, state_dir: str | Path | None = None) -> None:
        self.state_dir = state_dir
        self.saw_event = False
        self.segment_texts: list[str] = []
        self.intermediate_segments: list[str] = []
        self.all_texts: list[str] = []
        self.thought_chunks: list[str] = []
        self._emitted_thoughts: set[str] = set()
        self._seen_tools: set[str] = set()
        self.errors: list[str] = []

    def _flush_thought(self, *, channel: str | None = None, job: str | None = None, emit_trail: bool = True) -> None:
        if not self.thought_chunks:
            return
        raw_t = "".join(self.thought_chunks).strip()
        self.thought_chunks.clear()
        if raw_t and emit_trail and raw_t not in self._emitted_thoughts:
            self._emitted_thoughts.add(raw_t)
            push_line(
                f"{ICON['think']} {sanitize(raw_t, limit=140)}",
                channel=channel,
                job=job,
                state_dir=self.state_dir,
            )

    def _flush_intermediate_text(self, *, channel: str | None = None, job: str | None = None, emit_trail: bool = True) -> None:
        if not self.segment_texts:
            return
        seg = "".join(self.segment_texts)
        self.segment_texts.clear()
        clean = seg.strip()
        if clean:
            self.intermediate_segments.append(seg)
            if emit_trail and clean not in self._emitted_thoughts:
                self._emitted_thoughts.add(clean)
                push_line(
                    f"{ICON['think']} {sanitize(clean, limit=140)}",
                    channel=channel,
                    job=job,
                    state_dir=self.state_dir,
                )

    def consume(
        self,
        raw: str,
        *,
        channel: str | None = None,
        job: str | None = None,
        emit_trail: bool = True,
    ) -> None:
        st = (raw or "").strip()
        if not st.startswith("{"):
            return
        try:
            ev = json.loads(st)
        except json.JSONDecodeError:
            return
        if not isinstance(ev, dict):
            return
        self.saw_event = True
        t = str(ev.get("type") or "")
        if t == "thought":
            data = str(ev.get("data") or "")
            if data:
                self.thought_chunks.append(data)
            return
        if t == "text":
            self._flush_thought(channel=channel, job=job, emit_trail=emit_trail)
            data = str(ev.get("data") or "")
            if data:
                self.all_texts.append(data)
                self.segment_texts.append(data)
            return
        if t == "tool_call":
            self._flush_thought(channel=channel, job=job, emit_trail=emit_trail)
            self._flush_intermediate_text(channel=channel, job=job, emit_trail=emit_trail)
            cid = str(ev.get("toolCallId") or "")
            if cid and cid in self._seen_tools:
                return
            if cid:
                self._seen_tools.add(cid)
            if emit_trail:
                tname = str(ev.get("toolName") or ev.get("title") or "tool")
                inp = ev.get("rawInput") if isinstance(ev.get("rawInput"), dict) else {}
                if tname == "run_terminal_command":
                    cmd = sanitize(str(inp.get("command") or inp.get("description") or "shell"), limit=60)
                    push_line(f"{ICON['shell']} `{cmd}`", channel=channel, job=job, state_dir=self.state_dir)
                elif tname == "read_file":
                    p = sanitize(str(inp.get("file_path") or inp.get("path") or "archivo"), limit=60)
                    push_line(f"{ICON['read']} leyendo {p}", channel=channel, job=job, state_dir=self.state_dir)
                elif tname in ("search_replace", "write_file"):
                    p = sanitize(str(inp.get("file_path") or inp.get("path") or "archivo"), limit=60)
                    push_line(f"{ICON['edit']} editando {p}", channel=channel, job=job, state_dir=self.state_dir)
                elif tname == "grep":
                    pat = sanitize(str(inp.get("pattern") or inp.get("query") or ""), limit=60)
                    push_line(f"{ICON['grep']} buscando “{pat}”", channel=channel, job=job, state_dir=self.state_dir)
                elif tname == "list_dir":
                    p = sanitize(str(inp.get("path") or "."), limit=60)
                    push_line(f"{ICON['ls']} listando {p}", channel=channel, job=job, state_dir=self.state_dir)
                else:
                    push_line(f"🔧 {sanitize(tname, limit=50)}", channel=channel, job=job, state_dir=self.state_dir)
            return
        if t == "error":
            self.errors.append(str(ev.get("message") or "error"))

    def final_text(self) -> str:
        post_tool = "".join(self.segment_texts).strip()
        if post_tool:
            return strip_live_progress_preamble(post_tool)
        full = "".join(self.all_texts).strip()
        if full:
            return strip_live_progress_preamble(full)
        if self.errors:
            return f"GrokCLI error: {self.errors[-1]}"
        return ""


class CodexStream:
    """Parse ``codex exec --json`` JSONL events."""

    def __init__(self, *, state_dir: str | Path | None = None) -> None:
        self.state_dir = state_dir
        self.saw_event = False
        self.segment_messages: list[str] = []
        self.intermediate_messages: list[str] = []
        self.all_messages: list[str] = []
        self.errors: list[str] = []

    def _flush_intermediate(self, *, channel: str | None = None, job: str | None = None, emit_trail: bool = True) -> None:
        if not self.segment_messages:
            return
        for msg in self.segment_messages:
            clean = msg.strip()
            if clean:
                self.intermediate_messages.append(clean)
                if emit_trail:
                    push_line(
                        f"{ICON['think']} {sanitize(clean, limit=140)}",
                        channel=channel,
                        job=job,
                        state_dir=self.state_dir,
                    )
        self.segment_messages.clear()

    def consume(
        self,
        raw: str,
        *,
        channel: str | None = None,
        job: str | None = None,
        emit_trail: bool = True,
    ) -> None:
        st = (raw or "").strip()
        if not st.startswith("{"):
            return
        try:
            ev = json.loads(st)
        except json.JSONDecodeError:
            return
        if not isinstance(ev, dict):
            return
        self.saw_event = True
        t = str(ev.get("type") or "")
        item = ev.get("item") if isinstance(ev.get("item"), dict) else {}
        itype = str(item.get("type") or "")
        if t == "item.completed" and itype == "agent_message":
            txt = str(item.get("text") or "").strip()
            if txt:
                self.all_messages.append(txt)
                self.segment_messages.append(txt)
            return
        if t == "item.completed" and itype == "reasoning":
            txt = str(item.get("text") or "").strip()
            if txt and emit_trail:
                push_line(f"{ICON['think']} {sanitize(txt, limit=140)}", channel=channel, job=job, state_dir=self.state_dir)
            return
        if t == "item.started" and itype in ("command_execution", "mcp_tool_call", "file_change", "web_search"):
            self._flush_intermediate(channel=channel, job=job, emit_trail=emit_trail)
            if emit_trail:
                if itype == "command_execution":
                    cmd = str(item.get("command") or "shell")
                    for pfx in ("/bin/bash -lc ", "/bin/sh -c ", "bash -lc "):
                        if cmd.startswith(pfx):
                            cmd = cmd[len(pfx) :].strip("'\"")
                    push_line(f"{ICON['shell']} `{sanitize(cmd, limit=60)}`", channel=channel, job=job, state_dir=self.state_dir)
                elif itype == "mcp_tool_call":
                    tname = str(item.get("tool") or item.get("name") or "mcp")
                    if tname != "discord_progress":
                        push_line(f"🔧 {sanitize(tname, limit=50)}", channel=channel, job=job, state_dir=self.state_dir)
                elif itype == "file_change":
                    push_line(f"{ICON['edit']} editando archivos", channel=channel, job=job, state_dir=self.state_dir)
                elif itype == "web_search":
                    q = sanitize(str(item.get("query") or ""), limit=60)
                    push_line(f"{ICON['web']} {q or 'web'}", channel=channel, job=job, state_dir=self.state_dir)
            return
        if t in ("error", "turn.failed"):
            msg = str(ev.get("message") or (ev.get("error") or {}).get("message") or "")
            if msg:
                self.errors.append(msg)

    def final_text(self) -> str:
        if self.segment_messages:
            return strip_live_progress_preamble("\n\n".join(self.segment_messages).strip())
        if self.all_messages:
            return strip_live_progress_preamble(self.all_messages[-1].strip())
        if self.errors:
            return f"Codex error: {self.errors[-1]}"
        return ""

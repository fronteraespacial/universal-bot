"""Tests for universal_bot.unified_progress.agy_trail."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from universal_bot.unified_progress import agy_trail as agy
from universal_bot.unified_progress.trail import write_marker


class TestAgyTrail(unittest.TestCase):
    def test_run_command_becomes_shell_step(self):
        step = {
            "step_index": 4,
            "state": "DONE",
            "step_type": "tool",
            "tool_name": "run_command",
            "tool_info": {"name": "run_command", "parameters": {"CommandLine": "agy models"}},
        }
        line, *_ = agy.line_for_step(step, seen_idx=set(), thought=False, drafted=False, saw_tool=False)
        self.assertIn("agy models", line or "")
        self.assertIn(agy.ICON["shell"], line or "")

    def test_view_file_becomes_read_step(self):
        step = {
            "step_index": 5,
            "state": "DONE",
            "step_type": "tool",
            "tool_name": "view_file",
            "tool_info": {"parameters": {"path": "dispatcher.py"}},
        }
        line, *_ = agy.line_for_step(step, seen_idx=set(), thought=False, drafted=False, saw_tool=False)
        self.assertIn("dispatcher.py", line or "")
        self.assertIn("leyendo", line or "")

    def test_active_then_done_is_one_step(self):
        seen: set = set()
        active = {
            "step_index": 2,
            "state": "ACTIVE",
            "step_type": "tool",
            "tool_name": "view_file",
            "tool_info": {"parameters": {"path": "cli_brains.py"}},
        }
        done = dict(active, state="DONE")
        first, *_ = agy.line_for_step(active, seen_idx=seen, thought=False, drafted=False, saw_tool=False)
        second, *_ = agy.line_for_step(done, seen_idx=seen, thought=False, drafted=False, saw_tool=True)
        self.assertIn("cli_brains.py", first or "")
        self.assertIsNone(second)

    def test_user_input_and_permission_are_silent(self):
        seen: set = set()
        line, *_ = agy.line_for_step(
            {"step_index": 0, "step_type": "user_input", "state": "DONE"},
            seen_idx=seen,
            thought=False,
            drafted=False,
            saw_tool=False,
        )
        self.assertIsNone(line)
        line, *_ = agy.line_for_step(
            {"step_index": 1, "step_type": "tool", "tool_name": "ask_permission", "state": "DONE"},
            seen_idx=seen,
            thought=False,
            drafted=False,
            saw_tool=False,
        )
        self.assertIsNone(line)

    def test_result_response_is_the_reply(self):
        stream = agy.AgyStream()
        stream.consume(
            json.dumps({
                "event": "step_update",
                "step_update": {
                    "step_index": 1,
                    "state": "DONE",
                    "step_type": "tool",
                    "tool_name": "run_command",
                    "tool_info": {"parameters": {"CommandLine": "agy models"}},
                },
            })
        )
        stream.consume(
            json.dumps({
                "event": "result",
                "result": {"status": "SUCCESS", "response": "Gemini 4 Argon está.\n"},
            })
        )
        raw = "\n".join([
            json.dumps({"event": "result", "result": {"status": "SUCCESS", "response": "Gemini 4 Argon está.\n"}}),
            "some stderr noise",
        ])
        self.assertEqual(agy.public_text(stream, raw), "Gemini 4 Argon está.")

    def test_plain_text_fallback_when_no_events(self):
        self.assertEqual(agy.public_text(agy.AgyStream(), "ok"), "ok")

    def test_wrapper_error_is_kept(self):
        self.assertTrue(agy.public_text(agy.AgyStream(), "Se cortó **AGY** por límite de pared.").startswith("Se cortó"))

    def test_push_line_writes_to_events_file(self):
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td)
            chan, job = "123456", "789012"
            write_marker(state_dir, chan, job, "msg1", ingest=True)
            ok = agy.push_line("🔧 test step", channel=chan, job=job, state_dir=state_dir)
            self.assertTrue(ok)
            events_f = state_dir / "live_trail" / f"{chan}__{job}.events.jsonl"
            self.assertTrue(events_f.is_file())
            content = events_f.read_text(encoding="utf-8")
            self.assertIn("test step", content)

    def test_pre_tool_narration_pushed_to_trail_and_stripped_from_reply(self):
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td)
            chan, job = "123456", "789012"
            write_marker(state_dir, chan, job, "msg1", ingest=True)
            stream = agy.AgyStream(state_dir=state_dir)
            stream.consume(
                json.dumps({
                    "event": "step_update",
                    "step_update": {
                        "step_index": 1,
                        "state": "DONE",
                        "step_type": "agent_response",
                        "text_delta": "Voy a revisar el script primero.\n",
                    },
                }),
                channel=chan,
                job=job,
            )
            stream.consume(
                json.dumps({
                    "event": "step_update",
                    "step_update": {
                        "step_index": 2,
                        "state": "DONE",
                        "step_type": "tool",
                        "tool_name": "run_command",
                        "tool_info": {"parameters": {"CommandLine": "echo hi"}},
                    },
                }),
                channel=chan,
                job=job,
            )
            stream.consume(
                json.dumps({
                    "event": "step_update",
                    "step_update": {
                        "step_index": 3,
                        "state": "DONE",
                        "step_type": "agent_response",
                        "text_delta": "Respuesta final limpia.\n",
                    },
                }),
                channel=chan,
                job=job,
            )
            stream.consume(
                json.dumps({
                    "event": "result",
                    "result": {
                        "status": "SUCCESS",
                        "response": "Voy a revisar el script primero.\nRespuesta final limpia.\n",
                    },
                }),
                channel=chan,
                job=job,
            )
            self.assertEqual(agy.public_text(stream, ""), "Respuesta final limpia.")
            events_f = state_dir / "live_trail" / f"{chan}__{job}.events.jsonl"
            events_txt = events_f.read_text(encoding="utf-8")
            self.assertIn("Voy a revisar el script primero.", events_txt)

    def test_cursor_opencode_grok_codex_streams_separate_intermediate_thoughts(self):
        from universal_bot.unified_progress.cli_streams import (
            CodexStream,
            CursorStream,
            GrokCliStream,
            OpenCodeStream,
        )

        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td)
            chan, job = "111", "222"
            write_marker(state_dir, chan, job, "m1", ingest=True)

            # 1. CursorStream
            cs = CursorStream(state_dir=state_dir)
            cs.consume(
                json.dumps({
                    "type": "assistant",
                    "message": {"content": [{"type": "text", "text": "Primer pensamiento."}]},
                }),
                channel=chan,
                job=job,
            )
            cs.consume(
                json.dumps({
                    "type": "tool_call",
                    "subtype": "started",
                    "call_id": "t1",
                    "tool_call": {"shellToolCall": {"args": {"command": "ls"}}},
                }),
                channel=chan,
                job=job,
            )
            cs.consume(
                json.dumps({
                    "type": "assistant",
                    "message": {"content": [{"type": "text", "text": "Resultado final."}]},
                }),
                channel=chan,
                job=job,
            )
            cs.consume(
                json.dumps({
                    "type": "result",
                    "is_error": False,
                    "result": "Primer pensamiento.Resultado final.",
                }),
                channel=chan,
                job=job,
            )
            self.assertEqual(cs.final_text(), "Resultado final.")

            # 2. OpenCodeStream
            os_stream = OpenCodeStream(state_dir=state_dir)
            os_stream.consume(
                json.dumps({"type": "text", "part": {"text": "Buscando archivo."}}),
                channel=chan,
                job=job,
            )
            os_stream.consume(
                json.dumps({
                    "type": "tool_use",
                    "part": {"type": "tool", "tool": "bash", "state": {"input": {"command": "pwd"}}},
                }),
                channel=chan,
                job=job,
            )
            os_stream.consume(
                json.dumps({"type": "text", "part": {"text": "Archivo encontrado."}}),
                channel=chan,
                job=job,
            )
            self.assertEqual(os_stream.final_text(), "Archivo encontrado.")

            # 3. GrokCliStream
            gs = GrokCliStream(state_dir=state_dir)
            gs.consume(json.dumps({"type": "thought", "data": "Pensando paso 1."}), channel=chan, job=job)
            gs.consume(json.dumps({"type": "text", "data": "Voy a correr echo."}), channel=chan, job=job)
            gs.consume(
                json.dumps({
                    "type": "tool_call",
                    "toolCallId": "c1",
                    "toolName": "run_terminal_command",
                    "rawInput": {"command": "echo ok"},
                }),
                channel=chan,
                job=job,
            )
            gs.consume(json.dumps({"type": "text", "data": "Echo completado."}), channel=chan, job=job)
            self.assertEqual(gs.final_text(), "Echo completado.")

            # 4. CodexStream
            cxs = CodexStream(state_dir=state_dir)
            cxs.consume(
                json.dumps({
                    "type": "item.completed",
                    "item": {"id": "i0", "type": "agent_message", "text": "Voy a verificar."},
                }),
                channel=chan,
                job=job,
            )
            cxs.consume(
                json.dumps({
                    "type": "item.started",
                    "item": {"id": "i1", "type": "command_execution", "command": "/bin/bash -lc 'ls'"},
                }),
                channel=chan,
                job=job,
            )
            cxs.consume(
                json.dumps({
                    "type": "item.completed",
                    "item": {"id": "i2", "type": "agent_message", "text": "Todo verificado."},
                }),
                channel=chan,
                job=job,
            )
            self.assertEqual(cxs.final_text(), "Todo verificado.")

            events_txt = (state_dir / "live_trail" / f"{chan}__{job}.events.jsonl").read_text(encoding="utf-8")
            self.assertIn("Primer pensamiento.", events_txt)
            self.assertIn("Buscando archivo.", events_txt)
            self.assertIn("Pensando paso 1.", events_txt)
            self.assertIn("Voy a correr echo.", events_txt)
            self.assertIn("Voy a verificar.", events_txt)

    def test_cursor_stream_thinking_deltas_emitted_to_trail(self):
        from universal_bot.unified_progress.cli_streams import CursorStream

        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td)
            chan, job = "333", "444"
            write_marker(state_dir, chan, job, "m2", ingest=True)

            cs = CursorStream(state_dir=state_dir)
            cs.consume(
                json.dumps({"type": "thinking", "subtype": "delta", "text": "Revisando configuración."}),
                channel=chan,
                job=job,
            )
            cs.consume(
                json.dumps({"type": "thinking", "subtype": "completed"}),
                channel=chan,
                job=job,
            )
            cs.consume(
                json.dumps({
                    "type": "tool_call",
                    "subtype": "started",
                    "call_id": "c1",
                    "tool_call": {"shellToolCall": {"args": {"command": "date"}}},
                }),
                channel=chan,
                job=job,
            )
            cs.consume(
                json.dumps({
                    "type": "assistant",
                    "message": {"content": [{"type": "text", "text": "**Todo listo.**"}]},
                }),
                channel=chan,
                job=job,
            )
            cs.consume(
                json.dumps({
                    "type": "result",
                    "is_error": False,
                    "result": "**Todo listo.**",
                }),
                channel=chan,
                job=job,
            )
            self.assertEqual(cs.final_text(), "**Todo listo.**")
            events_txt = (state_dir / "live_trail" / f"{chan}__{job}.events.jsonl").read_text(encoding="utf-8")
            lines = [json.loads(ln)["line"] for ln in events_txt.splitlines() if ln.strip()]
            self.assertTrue(any("Revisando configuración." in l for l in lines))

    def test_strip_live_progress_preamble_varieties(self):
        from universal_bot.unified_progress.agy_trail import strip_live_progress_preamble

        text = (
            "Wait cancelled (task-435 is completing).\n"
            "No further action needed right now. Awaiting completion of SCP transfer.\n"
            "I have initiated the restart of the listener.\n"
            "I am waiting for the status check to complete.\n"
            "I will pause and let the status check finish.\n"
            "I will wait for the health check to complete.\n"
            "**Listo** (<@123>). Cambios listos."
        )
        self.assertEqual(strip_live_progress_preamble(text), "**Listo** (<@123>). Cambios listos.")


if __name__ == "__main__":
    unittest.main()

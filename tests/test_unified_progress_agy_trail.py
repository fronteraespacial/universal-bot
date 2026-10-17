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


if __name__ == "__main__":
    unittest.main()

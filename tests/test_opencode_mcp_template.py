"""Unit tests for per-bot opencode.json / skills templates."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from universal_bot.opencode.mcp_template import (
    render_get_time_skill,
    render_opencode_json,
    render_pack_rules_skill,
    render_run_mcp_sh,
    write_bot_opencode_layout,
)


class TestMcpTemplate(unittest.TestCase):
    def test_opencode_json_valid(self) -> None:
        text = render_opencode_json(
            bot_slug="acme",
            run_mcp_path="/opt/bots/acme/run_mcp.sh",
            path_env="/opt/bots/acme/.venv/bin:/usr/bin",
        )
        data = json.loads(text)
        self.assertIn("mcp", data)
        self.assertEqual(data["mcp"]["acme"]["type"], "local")
        self.assertNotIn("frontera", text.lower())
        self.assertNotIn("fe-bot", text.lower())

    def test_run_mcp_sh(self) -> None:
        sh = render_run_mcp_sh(
            bot_root="/opt/bots/acme",
            python_bin="/opt/bots/acme/.venv/bin/python",
            mcp_server="/opt/bots/acme/mcp_server.py",
        )
        self.assertIn("exec ", sh)
        self.assertIn("/opt/bots/acme/mcp_server.py", sh)

    def test_skills_generic(self) -> None:
        rules = render_pack_rules_skill(
            bot_slug="acme", agents_md="/opt/bots/acme/AGENTS.md"
        )
        self.assertIn("acme-pack-rules", rules)
        self.assertIn("get_current_time", rules)
        time_sk = render_get_time_skill(bot_slug="acme")
        self.assertIn("get_current_time", time_sk)
        self.assertNotIn("LAB3", rules)
        self.assertNotIn("922953", rules)

    def test_write_layout(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            paths = write_bot_opencode_layout(
                Path(td),
                bot_slug="acme",
                bot_root="/opt/bots/acme",
                python_bin="/opt/bots/acme/.venv/bin/python",
                mcp_server="/opt/bots/acme/mcp_server.py",
                path_env="/opt/bots/acme/.venv/bin",
                agents_md="/opt/bots/acme/AGENTS.md",
            )
            self.assertTrue(paths["opencode_json"].is_file())
            self.assertTrue(paths["run_mcp_sh"].is_file())
            self.assertTrue(paths["pack_rules"].is_file())
            self.assertTrue(paths["get_time"].is_file())
            data = json.loads(paths["opencode_json"].read_text(encoding="utf-8"))
            self.assertIn("acme", data["mcp"])


if __name__ == "__main__":
    unittest.main()

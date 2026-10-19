"""Unit tests for opencode run argv / env planning."""

from __future__ import annotations

import unittest

from universal_bot.opencode.env import OpenCodeEnv
from universal_bot.opencode.run import build_run_argv, plan_run, prepare_run_env


class TestRun(unittest.TestCase):
    def test_free_serve_argv(self) -> None:
        s = OpenCodeEnv(use_serve=True, port=49374)
        argv = build_run_argv("hola", model="big-pickle", tier="free", effort="low", settings=s)
        self.assertEqual(argv[0], "opencode")
        self.assertIn("run", argv)
        self.assertIn("--server", argv)
        self.assertIn("http://127.0.0.1:49374", argv)
        self.assertIn("--auto", argv)
        self.assertIn("opencode/deepseek-v4.1-flash-free#low", argv)
        self.assertNotIn("--standalone", argv)

    def test_go_serve_argv(self) -> None:
        s = OpenCodeEnv(use_serve=True)
        argv = build_run_argv(
            "hola", model="deepseek-v4.1-flash", tier="go", effort="high", settings=s
        )
        self.assertIn("opencode-go/deepseek-v4.1-flash#high", argv)

    def test_standalone_when_disabled(self) -> None:
        s = OpenCodeEnv(use_serve=False)
        argv = build_run_argv("x", model="deepseek-v4.1-flash-free", settings=s)
        self.assertIn("--standalone", argv)
        self.assertNotIn("--server", argv)

    def test_prepare_env_injects_config_and_password(self) -> None:
        s = OpenCodeEnv(
            use_serve=True,
            config_dir="/tmp/bot-a",
            config_file="/tmp/bot-a/opencode.json",
        )
        env = prepare_run_env(
            s,
            base={"PATH": "/usr/bin"},
            password="secret-test-only",
            lookup_password=False,
        )
        self.assertEqual(env["OPENCODE_CONFIG_DIR"], "/tmp/bot-a")
        self.assertEqual(env["OPENCODE_CONFIG"], "/tmp/bot-a/opencode.json")
        self.assertEqual(env["OPENCODE_PASSWORD"], "secret-test-only")

    def test_plan_run_flags_pty(self) -> None:
        s = OpenCodeEnv(require_pty_for_auto=True)
        plan = plan_run("ping", model="deepseek-v4.1-flash-free", settings=s, lookup_password=False)
        self.assertTrue(plan.use_pty)
        self.assertTrue(plan.use_auto)
        self.assertEqual(plan.serve_url, "http://127.0.0.1:49374")


if __name__ == "__main__":
    unittest.main()

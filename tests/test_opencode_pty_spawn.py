"""Unit tests for PTY availability and pipe fallback."""

from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from universal_bot.opencode.pty_spawn import PtyUnavailable, pty_available, spawn_with_pty


class TestPty(unittest.TestCase):
    def test_pty_available_posix(self) -> None:
        if sys.platform == "win32":
            self.skipTest("posix-only assertion")
        self.assertTrue(pty_available())

    def test_spawn_echo_with_pty(self) -> None:
        if sys.platform == "win32":
            self.skipTest("posix pty")
        result = spawn_with_pty(
            [sys.executable, "-c", "print('pty-ok')"],
            timeout_s=10,
            require_pty=True,
        )
        self.assertFalse(result.timed_out)
        self.assertEqual(result.returncode, 0)
        self.assertIn("pty-ok", result.stdout)

    def test_windows_without_pywinpty_raises(self) -> None:
        with patch("universal_bot.opencode.pty_spawn.sys") as fake_sys:
            fake_sys.platform = "win32"
            # Force import failures inside _spawn_windows by calling the
            # public API with require_pty after patching platform check path.
            with patch(
                "universal_bot.opencode.pty_spawn._spawn_windows",
                side_effect=PtyUnavailable("no conpty"),
            ):
                with self.assertRaises(PtyUnavailable):
                    spawn_with_pty(["echo"], require_pty=True)

    def test_pipe_fallback_when_not_required(self) -> None:
        result = spawn_with_pty(
            [sys.executable, "-c", "print('pipes-ok')"],
            timeout_s=10,
            require_pty=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("pipes-ok", result.stdout)


if __name__ == "__main__":
    unittest.main()

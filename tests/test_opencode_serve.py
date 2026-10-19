"""Unit tests for serve healthcheck / password / restart hints."""

from __future__ import annotations

import io
import json
import unittest
from unittest.mock import MagicMock

from universal_bot.opencode.env import OpenCodeEnv
from universal_bot.opencode.serve import (
    healthcheck,
    lookup_serve_password,
    restart_serve_hint,
)


class _FakeResp:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode()

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *args: object) -> None:
        return None


class TestServe(unittest.TestCase):
    def test_healthcheck_ok(self) -> None:
        s = OpenCodeEnv(port=49374)

        def opener(req: object, timeout: float = 3.0) -> _FakeResp:
            return _FakeResp({"healthy": True, "version": "1.2.3"})

        h = healthcheck(s, opener=opener)
        self.assertTrue(h.ok)
        self.assertEqual(h.version, "1.2.3")
        self.assertIn("/global/health", h.url)

    def test_healthcheck_down(self) -> None:
        import urllib.error

        s = OpenCodeEnv()

        def opener(req: object, timeout: float = 3.0) -> _FakeResp:
            raise urllib.error.URLError("refused")

        h = healthcheck(s, opener=opener)
        self.assertFalse(h.ok)
        self.assertTrue(h.detail)

    def test_lookup_password_from_env(self) -> None:
        pw = lookup_serve_password(
            environ={"OPENCODE_PASSWORD": "from-env"},
            runner=lambda: "should-not-run",
        )
        self.assertEqual(pw, "from-env")

    def test_lookup_password_from_cli(self) -> None:
        pw = lookup_serve_password(environ={}, runner=lambda: "cli-pw\n")
        self.assertEqual(pw, "cli-pw")

    def test_restart_hint(self) -> None:
        hint = restart_serve_hint(OpenCodeEnv(port=49374))
        self.assertEqual(hint["linux_systemd_user"][0], "systemctl")
        self.assertIn("restart", hint["linux_systemd_user"])
        self.assertEqual(hint["cli_serve_foreground"][1], "serve")
        self.assertIn("127.0.0.1", hint["cli_serve_foreground"])


if __name__ == "__main__":
    unittest.main()

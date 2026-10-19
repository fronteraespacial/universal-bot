"""Unit tests for UB_OPENCODE_* env parsing."""

from __future__ import annotations

import unittest

from universal_bot.opencode.env import load_opencode_env


class TestOpenCodeEnv(unittest.TestCase):
    def test_defaults(self) -> None:
        s = load_opencode_env({})
        self.assertTrue(s.use_serve)
        self.assertEqual(s.host, "127.0.0.1")
        self.assertEqual(s.port, 49374)
        self.assertEqual(s.free_model, "deepseek-v4.1-flash-free")
        self.assertEqual(s.serve_url, "http://127.0.0.1:49374")

    def test_overrides(self) -> None:
        s = load_opencode_env(
            {
                "UB_OPENCODE_USE_SERVE": "0",
                "UB_OPENCODE_PORT": "4123",
                "UB_OPENCODE_FREE_MODEL": "glm-5.3-flash-free",
                "UB_OPENCODE_CONFIG_DIR": "/tmp/bot-oc",
                "UB_OPENCODE_CONFIG": "/tmp/bot-oc/opencode.json",
            }
        )
        self.assertFalse(s.use_serve)
        self.assertEqual(s.port, 4123)
        self.assertEqual(s.free_model, "glm-5.3-flash-free")
        self.assertEqual(s.config_dir, "/tmp/bot-oc")
        self.assertEqual(s.config_file, "/tmp/bot-oc/opencode.json")

    def test_rejects_wildcard_host(self) -> None:
        s = load_opencode_env({"UB_OPENCODE_HOST": "0.0.0.0"})
        self.assertEqual(s.host, "127.0.0.1")

    def test_ignores_fe_aliases(self) -> None:
        s = load_opencode_env(
            {
                "FE_OPENCODE_USE_SERVE": "0",
                "FE_OPENCODE_PORT": "1",
                "UB_OPENCODE_PORT": "5555",
            }
        )
        self.assertTrue(s.use_serve)  # FE_ ignored
        self.assertEqual(s.port, 5555)

    def test_bad_port_falls_back(self) -> None:
        s = load_opencode_env({"UB_OPENCODE_PORT": "nope"})
        self.assertEqual(s.port, 49374)


if __name__ == "__main__":
    unittest.main()

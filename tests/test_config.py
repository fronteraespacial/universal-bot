import tempfile
import unittest
from pathlib import Path

from universal_bot.config import load_instance_config, parse_secrets_env


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.tmp_dir.name)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_deny_by_default_when_allowlist_empty(self):
        toml_path = self.base_path / "instance.toml"
        toml_path.write_text(
            """
            schema_version = 1
            [meta]
            instance_name = "test-node"

            [discord]
            guild_id = "12345"
            bot_id = "67890"
            allowlist_ids = []
            """,
            encoding="utf-8",
        )

        cfg = load_instance_config(toml_path)
        self.assertFalse(cfg.is_user_authorized("99999"))
        allowed, reason = cfg.is_execution_allowed(author_id="99999", channel_id="111", guild_id="12345")
        self.assertFalse(allowed)
        self.assertIn("deny-by-default", reason)

    def test_allowlist_permits_configured_users(self):
        toml_path = self.base_path / "instance.toml"
        toml_path.write_text(
            """
            schema_version = 1
            [discord]
            guild_id = "12345"
            bot_id = "67890"
            allowlist_ids = ["329811958603972609", "363744726773530625"]
            """,
            encoding="utf-8",
        )

        cfg = load_instance_config(toml_path)
        self.assertTrue(cfg.is_user_authorized("329811958603972609"))
        self.assertTrue(cfg.is_user_authorized("363744726773530625"))
        self.assertFalse(cfg.is_user_authorized("111111111111111111"))

        allowed, _ = cfg.is_execution_allowed(author_id="329811958603972609", channel_id="222", guild_id="12345")
        self.assertTrue(allowed)

    def test_channel_filtering(self):
        toml_path = self.base_path / "instance.toml"
        toml_path.write_text(
            """
            schema_version = 1
            [discord]
            guild_id = "12345"
            bot_id = "67890"
            allowlist_ids = ["100"]
            allowed_channel_ids = ["chan-1", "chan-2"]
            """,
            encoding="utf-8",
        )

        cfg = load_instance_config(toml_path)
        self.assertTrue(cfg.is_channel_allowed("chan-1"))
        self.assertFalse(cfg.is_channel_allowed("chan-3"))
        # Thread inheritance
        self.assertTrue(cfg.is_channel_allowed("thread-x", parent_channel_id="chan-2"))

    def test_path_resolution_relative_to_instance_dir(self):
        inst_dir = self.base_path / "my_instance"
        inst_dir.mkdir()
        toml_path = inst_dir / "instance.toml"
        toml_path.write_text(
            """
            schema_version = 1
            [discord]
            guild_id = "123"
            bot_id = "456"

            [paths]
            state_dir = "./custom_state"
            jobs_dir = "./custom_state/jobs"
            """,
            encoding="utf-8",
        )

        cfg = load_instance_config(toml_path)
        self.assertEqual(cfg.paths.instance_dir, inst_dir.resolve())
        self.assertEqual(cfg.paths.state_dir, (inst_dir / "custom_state").resolve())
        self.assertEqual(cfg.paths.jobs_dir, (inst_dir / "custom_state/jobs").resolve())

    def test_parse_secrets_env(self):
        env_file = self.base_path / "secrets.env"
        env_file.write_text(
            """
            # Comments should be ignored
            DISCORD_BOT_TOKEN="my-secret-token-123"
            CONTEXT7_API_KEY='ctx7-key-456'
            UNQUOTED_VAL=simple_val
            EMPTY_VAL=
            INVALID_LINE_NO_EQUALS
            """,
            encoding="utf-8",
        )

        secrets = parse_secrets_env(env_file)
        self.assertEqual(secrets["DISCORD_BOT_TOKEN"], "my-secret-token-123")
        self.assertEqual(secrets["CONTEXT7_API_KEY"], "ctx7-key-456")
        self.assertEqual(secrets["UNQUOTED_VAL"], "simple_val")
        self.assertEqual(secrets["EMPTY_VAL"], "")
        self.assertNotIn("INVALID_LINE_NO_EQUALS", secrets)


if __name__ == "__main__":
    unittest.main()

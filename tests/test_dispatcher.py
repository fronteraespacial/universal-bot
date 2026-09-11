import tempfile
import unittest
from pathlib import Path

from universal_bot.config import load_instance_config
from universal_bot.contracts import JobStatus
from universal_bot.dispatcher import Dispatcher
from universal_bot.store import JobStore


class TestDispatcher(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.tmp_dir.name)

        # Config setup
        toml_path = self.base_path / "instance.toml"
        toml_path.write_text(
            """
            schema_version = 1
            [meta]
            instance_name = "test-node"

            [discord]
            guild_id = "1001"
            bot_id = "2001"
            allowlist_ids = ["5001"]

            [runtime]
            default_brain = "agy"
            max_concurrent_jobs = 1
            max_pending_jobs = 5
            """,
            encoding="utf-8",
        )
        self.config = load_instance_config(toml_path)
        self.store = JobStore(self.base_path / "jobs.sqlite")
        self.dispatcher = Dispatcher(self.config, self.store)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_admit_unauthorized_user_denied(self):
        job, admitted, reason = self.dispatcher.admit_request(
            author_id="9999",  # Unauthorized
            channel_id="chan-1",
            message_id="m1",
            prompt="do something",
            guild_id="1001",
        )
        self.assertFalse(admitted)
        self.assertIsNone(job)
        self.assertIn("admission_denied", reason)

    def test_admit_authorized_user_succeeds(self):
        job, admitted, reason = self.dispatcher.admit_request(
            author_id="5001",  # Authorized in allowlist
            channel_id="chan-1",
            message_id="m1",
            prompt="valid task",
            guild_id="1001",
        )
        self.assertTrue(admitted)
        self.assertIsNotNone(job)
        self.assertEqual(reason, "admitted")
        self.assertEqual(job.brain, "agy")

        # Claim job
        claimed = self.dispatcher.claim_next("worker-alpha")
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.job_id, job.job_id)

        # Mark completed
        ok = self.dispatcher.mark_completed(claimed.job_id, JobStatus.SUCCEEDED, exit_code=0, output="result")
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()

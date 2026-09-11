import tempfile
import time
import unittest
from pathlib import Path

from universal_bot.contracts import DeliveryStatus, JobRequest, JobStatus
from universal_bot.store import JobStore


class TestJobStore(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_jobs.sqlite"
        self.store = JobStore(self.db_path)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_admit_and_deduplication(self):
        req1 = JobRequest.create(
            instance_name="site1",
            message_id="msg_1001",
            guild_id="g1",
            channel_id="c1",
            author_id="a1",
            prompt="Hello 1",
            brain="agy",
            workspace_dir="/tmp/ws1",
        )
        job, admitted, reason = self.store.admit_job(req1)
        self.assertTrue(admitted)
        self.assertEqual(reason, "admitted")
        self.assertEqual(job.job_id, req1.job_id)

        # Duplicate message_id
        req2 = JobRequest.create(
            instance_name="site1",
            message_id="msg_1001",  # Same message ID
            guild_id="g1",
            channel_id="c1",
            author_id="a1",
            prompt="Hello 2 duplicate",
            brain="agy",
            workspace_dir="/tmp/ws1",
        )
        job2, admitted2, reason2 = self.store.admit_job(req2)
        self.assertFalse(admitted2)
        self.assertEqual(reason2, "duplicate_message_id")
        self.assertEqual(job2.job_id, req1.job_id)

    def test_queue_capacity_limit(self):
        for i in range(3):
            req = JobRequest.create(
                instance_name="site1",
                message_id=f"msg_{i}",
                guild_id="g1",
                channel_id=f"c_{i}",
                author_id="a1",
                prompt="work",
                brain="agy",
                workspace_dir=f"/tmp/ws_{i}",
            )
            _, admitted, _ = self.store.admit_job(req, max_pending=3)
            self.assertTrue(admitted)

        # 4th request must be rejected as queue_full
        overflow_req = JobRequest.create(
            instance_name="site1",
            message_id="msg_overflow",
            guild_id="g1",
            channel_id="c_overflow",
            author_id="a1",
            prompt="work",
            brain="agy",
            workspace_dir="/tmp/ws_overflow",
        )
        _, admitted, reason = self.store.admit_job(overflow_req, max_pending=3)
        self.assertFalse(admitted)
        self.assertEqual(reason, "queue_full")

    def test_fifo_claiming_and_conversation_mutex(self):
        # Two jobs in the same channel
        req1 = JobRequest.create(
            instance_name="site1",
            message_id="m1",
            guild_id="g1",
            channel_id="shared_channel",
            author_id="a1",
            prompt="First in channel",
            brain="agy",
            workspace_dir="/tmp/ws1",
        )
        req2 = JobRequest.create(
            instance_name="site1",
            message_id="m2",
            guild_id="g1",
            channel_id="shared_channel",
            author_id="a1",
            prompt="Second in channel",
            brain="agy",
            workspace_dir="/tmp/ws2",
        )
        self.store.admit_job(req1)
        time.sleep(0.01)
        self.store.admit_job(req2)

        # Claim first job
        claimed1 = self.store.claim_next_job(lease_owner="worker-1", max_concurrent=2)
        self.assertIsNotNone(claimed1)
        self.assertEqual(claimed1.job_id, req1.job_id)

        # Claiming second job by another worker must return None because shared_channel is locked!
        claimed2 = self.store.claim_next_job(lease_owner="worker-2", max_concurrent=2)
        self.assertIsNone(claimed2)

        # Finish first job
        self.store.finish_job(claimed1.job_id, JobStatus.SUCCEEDED, exit_code=0, output="done")

        # Now second job can be claimed
        claimed3 = self.store.claim_next_job(lease_owner="worker-2", max_concurrent=2)
        self.assertIsNotNone(claimed3)
        self.assertEqual(claimed3.job_id, req2.job_id)

    def test_recover_abandoned_jobs(self):
        req = JobRequest.create(
            instance_name="site1",
            message_id="m_crash",
            guild_id="g1",
            channel_id="c1",
            author_id="a1",
            prompt="Crash me",
            brain="agy",
            workspace_dir="/tmp/ws",
        )
        self.store.admit_job(req)
        claimed = self.store.claim_next_job(lease_owner="worker-dead", max_concurrent=1)
        self.assertIsNotNone(claimed)

        # Simulate time passing beyond lease_timeout_s (e.g. 1 second timeout)
        time.sleep(0.05)
        interrupted = self.store.recover_abandoned_jobs(lease_timeout_s=0.01)
        self.assertIn(req.job_id, interrupted)

        # Status must be INTERRUPTED, not failed or succeeded
        status = self.store.get_job_status(req.job_id)
        self.assertEqual(status, JobStatus.INTERRUPTED)

    def test_outbox_flow(self):
        req = JobRequest.create(
            instance_name="site1",
            message_id="m_out",
            guild_id="g1",
            channel_id="c_out",
            author_id="a1",
            prompt="Hello out",
            brain="agy",
            workspace_dir="/tmp/ws",
        )
        self.store.admit_job(req)

        out_id = self.store.enqueue_outbox(
            job_id=req.job_id,
            channel_id="c_out",
            message_id="m_out",
            payload={"content": "Final result from model"},
        )
        self.assertTrue(out_id.startswith("out_"))

        pending = self.store.fetch_pending_outbox()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["outbox_id"], out_id)
        self.assertEqual(pending[0]["payload"]["content"], "Final result from model")

        # Mark delivered
        self.store.mark_outbox_delivered(out_id)
        pending_after = self.store.fetch_pending_outbox()
        self.assertEqual(len(pending_after), 0)


if __name__ == "__main__":
    unittest.main()

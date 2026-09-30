"""Universal Bot consumes progress_contract via ProgressScheduler."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path("/workspace/fe-bot-discord")))
sys.path.insert(0, str(Path("/workspace/universal-bot/src")))

from universal_bot.config import RuntimeConfig
from universal_bot.progress import ProgressScheduler, freshness_window_s


class TestUbProgressContract(unittest.TestCase):
    def test_runtime_defaults(self):
        rt = RuntimeConfig()
        self.assertEqual(rt.progress_interval_s, 120)
        self.assertEqual(rt.progress_freshness_s, 180)
        self.assertEqual(freshness_window_s(), 180)

    def test_scheduler_short_job_and_blocker(self):
        sched = ProgressScheduler(clock=lambda: 0.0)
        short = sched.observe(
            {
                "version": 1,
                "job_id": "ub-1",
                "channel_id": "c",
                "event_id": "t1",
                "seq": 1,
                "agent": "AGY",
                "event": "tick",
                "pct": 10,
                "detail": "corto",
                "started_at": 0.0,
                "deadline_at": 1800.0,
            },
            now=20.0,
        )
        self.assertFalse(short.publish)
        blocker = sched.observe(
            {
                "version": 1,
                "job_id": "ub-1",
                "channel_id": "c",
                "event_id": "b1",
                "seq": 2,
                "agent": "AGY",
                "event": "blocker",
                "pct": 10,
                "detail": "traba",
                "next_action": "pedir ayuda",
                "started_at": 0.0,
                "deadline_at": 1800.0,
                "evidence": "tool fail",
            },
            now=70.0,
        )
        self.assertTrue(blocker.publish)
        self.assertLessEqual(len(blocker.text.encode("utf-16-le")) // 2, 200)
        self.assertIn("BLOQUEADO", blocker.text)


if __name__ == "__main__":
    unittest.main()

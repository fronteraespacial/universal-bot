"""Unit tests for real activity and multi-signal stall detection in universal_bot."""
import os
import tempfile
import time
import unittest
from pathlib import Path

from universal_bot.activity import (
    ActivitySignal,
    RealActivityMonitor,
    get_dir_newest_mtime,
    is_pid_alive,
    real_activity_seen,
)


class TestRealActivityMonitor(unittest.TestCase):
    def setUp(self):
        self.now = 100000.0
        self.monitor = RealActivityMonitor(
            stall_threshold_s=180.0,
            progress_freshness_s=360.0,
            workspace_freshness_s=360.0,
            initial_activity_ts=self.now,
        )

    def test_stderr_growth_resets_idle(self):
        # Time passes (200s > 180s stall threshold)
        t = self.now + 200.0
        # But stderr grew from 0 to 50 bytes
        report = self.monitor.evaluate(now=t, stderr_size=50, stdout_size=0)
        self.assertTrue(report.active)
        self.assertEqual(report.signal, ActivitySignal.STDERR)
        self.assertEqual(report.idle_seconds, 0.0)
        self.assertEqual(self.monitor.snapshot.last_stderr_size, 50)

    def test_stdout_growth_resets_idle(self):
        t = self.now + 250.0
        # stderr is quiet (0), but stdout grew to 120 bytes
        report = self.monitor.evaluate(now=t, stderr_size=0, stdout_size=120)
        self.assertTrue(report.active)
        self.assertEqual(report.signal, ActivitySignal.STDOUT)
        self.assertEqual(report.idle_seconds, 0.0)
        self.assertEqual(self.monitor.snapshot.last_stdout_size, 120)

    def test_progress_freshness_prevents_stall(self):
        # Simulation of incident: stderr quiet (still 79 bytes), stdout quiet
        self.monitor.snapshot.last_stderr_size = 79
        self.monitor.snapshot.last_stdout_size = 10
        t = self.now + 200.0  # 200s without stream I/O (> 180s stall threshold)

        # Discord progress occurred at t - 60s (age = 60s < 360s progress_freshness_s)
        report = self.monitor.evaluate(
            now=t,
            stderr_size=79,
            stdout_size=10,
            external_progress_ts=t - 60.0,
        )
        self.assertTrue(report.active)
        self.assertEqual(report.signal, ActivitySignal.PROGRESS)
        self.assertEqual(report.idle_seconds, 0.0)

    def test_workspace_mtime_prevents_stall(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td) / "workspace"
            ws.mkdir()
            sub = ws / "build"
            sub.mkdir()
            file1 = sub / "out.json"
            file1.write_text('{"step": 1}', encoding="utf-8")

            t = self.now + 200.0
            # External progress absent, streams quiet, but files changed under workspace
            report = self.monitor.evaluate(
                now=t,
                stderr_size=0,
                stdout_size=0,
                workspace_dir=ws,
            )
            self.assertTrue(report.active)
            self.assertEqual(report.signal, ActivitySignal.WORKSPACE_MTIME)
            self.assertEqual(report.idle_seconds, 0.0)

    def test_sibling_pid_prevents_stall(self):
        current_pid = os.getpid()
        self.assertTrue(is_pid_alive(current_pid))

        t = self.now + 240.0
        # Orchestrator is completely quiet, but sibling CLI PID is alive
        report = self.monitor.evaluate(
            now=t,
            stderr_size=0,
            stdout_size=0,
            sibling_pids=[current_pid],
        )
        self.assertTrue(report.active)
        self.assertEqual(report.signal, ActivitySignal.SIBLING_CLI)
        self.assertEqual(report.idle_seconds, 0.0)

    def test_child_pid_prevents_stall(self):
        current_pid = os.getpid()
        t = self.now + 240.0
        report = self.monitor.evaluate(
            now=t,
            stderr_size=0,
            stdout_size=0,
            child_pids=[current_pid],
        )
        self.assertTrue(report.active)
        self.assertEqual(report.signal, ActivitySignal.CHILD_PROCESS)
        self.assertEqual(report.idle_seconds, 0.0)

    def test_explicit_renew_resets_idle(self):
        t = self.now + 280.0
        renew_report = self.monitor.renew(now=t, reason="User sent +30 / job_extend")
        self.assertTrue(renew_report.active)
        self.assertEqual(renew_report.signal, ActivitySignal.LEASE_RENEW)
        self.assertEqual(renew_report.idle_seconds, 0.0)
        self.assertEqual(self.monitor.snapshot.last_activity_ts, t)

    def test_stall_triggers_when_all_signals_idle(self):
        # 190s pass without ANY signal
        t = self.now + 190.0
        report = self.monitor.evaluate(
            now=t,
            stderr_size=0,
            stdout_size=0,
            external_progress_ts=0.0,
            workspace_dir=None,
            sibling_pids=[],
            child_pids=[],
        )
        # Should be marked inactive / stalled because idle_seconds (190) >= stall_threshold_s (180)
        self.assertFalse(report.active)
        self.assertEqual(report.signal, ActivitySignal.NONE)
        self.assertGreaterEqual(report.idle_seconds, 190.0)

    def test_functional_helper_real_activity_seen(self):
        now = time.time()
        # Case 1: Stderr growth
        active, meta = real_activity_seen(
            now=now,
            stall_s=180.0,
            last_activity=now - 200.0,
            stderr_size=100,
            last_stderr_size=20,
        )
        self.assertTrue(active)
        self.assertEqual(meta["signal"], "stderr")

        # Case 2: Progress TS within fresh window
        active, meta = real_activity_seen(
            now=now,
            stall_s=180.0,
            last_activity=now - 200.0,
            stderr_size=20,
            last_stderr_size=20,
            progress_ts=now - 120.0,
            progress_fresh_s=360.0,
        )
        self.assertTrue(active)
        self.assertEqual(meta["signal"], "external_progress")

        # Case 3: Completely dead
        active, meta = real_activity_seen(
            now=now,
            stall_s=180.0,
            last_activity=now - 200.0,
            stderr_size=20,
            last_stderr_size=20,
            progress_ts=0.0,
        )
        self.assertFalse(active)
        self.assertEqual(meta["signal"], "none")


class TestUtils(unittest.TestCase):
    def test_get_dir_newest_mtime(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            f = base / "test.txt"
            f.write_text("hello", encoding="utf-8")
            mtime = get_dir_newest_mtime(base)
            self.assertGreater(mtime, 0.0)
            self.assertAlmostEqual(mtime, f.stat().st_mtime, delta=0.5)

    def test_is_pid_alive_invalid(self):
        self.assertFalse(is_pid_alive(-1))
        self.assertFalse(is_pid_alive(0))
        # Very high PID that likely doesn't exist
        self.assertFalse(is_pid_alive(9999999))


if __name__ == "__main__":
    unittest.main()

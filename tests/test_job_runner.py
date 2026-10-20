"""El job runner deja prompt, salidas y meta. El timeout no tira lo ya impreso."""

import json
import sys
from datetime import datetime, timezone

from universal_bot.code_mode.clock import FakeClock
from universal_bot.code_mode.job_runner import JobRunner

T0 = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def test_local_command_writes_the_job_dir(tmp_path):
    runner = JobRunner(tmp_path / "jobs", FakeClock(T0))
    result = runner.run(
        slug="eco",
        command=[sys.executable, "-c", "print('eco')"],
        cwd=tmp_path,
        prompt="imprimí eco",
        timeout_s=5,
    )
    assert result.directory.name == "20261020T120000-eco"
    assert (result.directory / "prompt.txt").read_text(encoding="utf-8") == "imprimí eco"
    assert "eco" in result.stdout
    assert result.exit_code == 0
    assert result.timed_out is False
    meta = json.loads((result.directory / "meta.json").read_text(encoding="utf-8"))
    assert meta["command"] == [sys.executable, "-c", "print('eco')"]
    assert meta["cwd"] == str(tmp_path)
    assert meta["start"] == T0.isoformat()
    assert meta["exit_code"] == 0
    assert meta["timed_out"] is False
    assert (result.directory / "stderr").is_file()


def test_timeout_keeps_partial_stdout_and_null_exit(tmp_path):
    runner = JobRunner(tmp_path / "jobs", FakeClock(T0))
    script = "import time; print('hola', flush=True); time.sleep(30)"
    result = runner.run(
        slug="lento",
        command=[sys.executable, "-c", script],
        cwd=tmp_path,
        prompt="esperá",
        timeout_s=0.5,
    )
    assert result.directory.name == "20261020T120000-lento"
    assert result.timed_out is True
    assert result.exit_code is None
    assert "hola" in result.stdout
    meta = json.loads((result.directory / "meta.json").read_text(encoding="utf-8"))
    assert meta["timed_out"] is True
    assert meta["exit_code"] is None
    assert "hola" in (result.directory / "stdout").read_text(encoding="utf-8")

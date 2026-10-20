"""El runtime arma el MAIN (warm) y los workers (lab en el sandbox) cuando main.enabled está prendido."""

from pathlib import Path

from universal_bot.code_mode.clock import FakeClock
from universal_bot.code_mode.config import CodeModeConfig
from universal_bot.code_mode.lab_runner import LabRunner
from universal_bot.code_mode.orchestrator import Orchestrator, ProcessWorker, WarmBrain
from universal_bot.labcode_runtime import build_orchestrator, main
from tests.test_lab_runner import T0, policy


def test_build_orchestrator_uses_a_warm_main_and_sandboxed_workers(tmp_path):
    runner = LabRunner(clock=FakeClock(T0), lab_root=tmp_path / "labs", routing_policy=policy(tmp_path))
    config = CodeModeConfig(main_enabled=True, main_cli="grok", main_model="grok-4.7")
    orch = build_orchestrator(FakeClock(T0), tmp_path / "mode.sqlite", config, runner, main_root=tmp_path / "main")
    assert isinstance(orch, Orchestrator)
    assert isinstance(orch.brain, WarmBrain)
    worker = orch.worker_factory("job-1", "probá algo")
    assert isinstance(worker, ProcessWorker)
    argv = worker.argv_for("probá algo")
    assert argv[0] == "bwrap" and "--unshare-all" in argv
    assert (Path(worker.cwd) / "prompt.txt").read_text(encoding="utf-8").startswith("Probá esta hipótesis")


def test_build_orchestrator_is_off_by_default(tmp_path):
    runner = LabRunner(clock=FakeClock(T0), lab_root=tmp_path / "labs", routing_policy=policy(tmp_path))
    assert build_orchestrator(FakeClock(T0), tmp_path / "mode.sqlite", CodeModeConfig(), runner) is None


def test_main_loop_passes_the_orchestrator(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setenv("UBLAB_CONFIG", "")
    monkeypatch.setattr("universal_bot.labcode_runtime.build_orchestrator", lambda *a, **k: "ORCH")
    monkeypatch.setattr("universal_bot.labcode_runtime.run_once", lambda *a, **k: seen.update(k))
    main(["--spool", str(tmp_path / "spool"), "--once", "--db", str(tmp_path / "m.sqlite")])
    assert seen.get("orchestrator") == "ORCH"


def _orch(tmp_path, **config):
    from tests.test_main_brains import SIDECAR
    runner = LabRunner(clock=FakeClock(T0), lab_root=tmp_path / "labs", routing_policy=policy(tmp_path))
    cfg = CodeModeConfig(main_enabled=True, **config)
    return build_orchestrator(FakeClock(T0), tmp_path / "mode.sqlite", cfg, runner, main_root=tmp_path / "main", sidecar=SIDECAR), runner


def test_default_main_is_cursor_sdk_with_fallback(tmp_path):
    from universal_bot.code_mode.main_brains import FallbackSession, ServeSidecarSession
    assert CodeModeConfig().main_cli == "auto"
    orch, _ = _orch(tmp_path)
    session = orch.brain.session_factory()
    assert isinstance(session, FallbackSession) and isinstance(session.primary, ServeSidecarSession)


def test_quota_file_routes_main_and_lab_to_cursor_agent(tmp_path):
    import json
    from universal_bot.code_mode.main_brains import RelaunchSession
    quota = tmp_path / "quota.json"
    quota.write_text(json.dumps({"grok_remaining": 0.38}), encoding="utf-8")
    orch, runner = _orch(tmp_path, main_cli="grok", quota_file=str(quota))
    assert isinstance(orch.brain.session_factory(), RelaunchSession)
    assert runner.quota is not None and runner.quota.grok_remaining() == 0.38


def test_low_grok_quota_moves_the_worker_to_cursor_agent(tmp_path):
    import json
    quota = tmp_path / "quota.json"
    quota.write_text(json.dumps({"grok_remaining": 0.38}), encoding="utf-8")
    orch, _ = _orch(tmp_path, quota_file=str(quota))
    argv = orch.worker_factory("job-1", "probá algo").argv_for("probá algo")
    assert "cursor-agent" in " ".join(argv) and "grok-4.7-high-fast" in argv

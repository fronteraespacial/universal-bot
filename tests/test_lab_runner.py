"""Lab runner: ruta, sandbox, parseo, presupuesto y Maverick. El CLI es falso."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from universal_bot.code_mode.clock import FakeClock
from universal_bot.code_mode.config import load_code_mode_config
from universal_bot.code_mode.job_runner import JobRun, JobRunner
from universal_bot.code_mode.lab_runner import (
    DEFAULT_ROUTING_POLICY,
    LabRunner,
    grok_command,
    parse_marked_block,
    resolve_route,
    sandbox_env,
)

T0 = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
APPROVE = {
    "hypothesis": "el audio entra en menos de un minuto",
    "commands": ["python probe.py"],
    "result": "40 segundos",
    "artifacts": ["probe.txt"],
    "verdict": "APPROVE",
    "evidence_class": "running",
}


def lab_line(payload) -> str:
    return "LAB_RESULT: " + json.dumps(payload)


def mav_line(payload) -> str:
    return "MAVERICK_RESULT: " + json.dumps(payload)


class ScriptedJobs:
    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.calls = []

    def run(self, *, slug, command, cwd, prompt, timeout_s, env=None, directory=None):
        self.calls.append(
            {
                "slug": slug,
                "command": list(command),
                "cwd": cwd,
                "prompt": prompt,
                "timeout_s": timeout_s,
                "env": env,
                "directory": directory,
            }
        )
        item = self.scripts.pop(0)
        if isinstance(item, Exception):
            raise item
        stdout, timed_out = item
        folder = Path(directory or cwd)
        code = None if timed_out else 0
        return JobRun(folder, code, timed_out, stdout, "")


def policy(tmp_path: Path) -> Path:
    path = tmp_path / "routing.yaml"
    path.write_text(
        """
routes:
  - id: lab-t2
    role: lab
    tier: [T2]
    chain:
      - {cli: grok, effort: medium}
      - {cli: grok, model: grok-4.7, effort: medium}
  - id: lab-t3
    role: lab
    tier: [T3]
    chain:
      - {cli: grok, model: grok-4.7, effort: high}
  - id: scout
    role: scout
    tier: [T2, T3]
    chain:
      - {cli: opencode, model: flash, effort: low}
""",
        encoding="utf-8",
    )
    return path


def runner(tmp_path, jobs, **kwargs):
    return LabRunner(
        clock=kwargs.pop("clock", FakeClock(T0)),
        lab_root=kwargs.pop("lab_root", tmp_path / "labs"),
        jobs=jobs,
        routing_policy=kwargs.pop("routing_policy", policy(tmp_path)),
        command_for=kwargs.pop("command_for", lambda route, labdir, kind: ["python", kind]),
        environ=kwargs.pop("environ", {"PATH": "/usr/bin", "HOME": "/tmp", "LANG": "C.UTF-8"}),
        **kwargs,
    )


def test_default_policy_path_is_the_catalog():
    assert DEFAULT_ROUTING_POLICY == "/workspace/codemode-base/catalog/routing-policy.yaml"


@pytest.mark.parametrize(
    ("role", "tier", "expected"),
    [
        ("lab", "T2", ("grok", "grok-4.7", "medium")),
        ("lab", "T3", ("grok", "grok-4.7", "high")),
        ("scout", "T2", ("opencode", "flash", "low")),
        ("maverick", "T2", ("grok", "grok-4.7", "medium")),
        ("lab", None, ("grok", "grok-4.7", "medium")),
    ],
)
def test_resolve_route_picks_the_first_usable_step(tmp_path, role, tier, expected):
    found = resolve_route(policy(tmp_path), role, tier=tier)
    assert (found.cli, found.model, found.effort) == expected


def test_missing_policy_falls_back_to_grok_medium(tmp_path):
    found = resolve_route(tmp_path / "no-esta.yaml", "lab", tier="T2")
    assert (found.cli, found.model, found.effort) == ("grok", "grok-4.7", "medium")


def test_empty_chain_falls_back(tmp_path):
    path = tmp_path / "vacio.yaml"
    path.write_text("routes:\n  - {role: lab, tier: [T2], chain: []}\n", encoding="utf-8")
    found = resolve_route(path, "lab", tier="T2")
    assert (found.cli, found.model, found.effort) == ("grok", "grok-4.7", "medium")


def test_grok_command_is_the_contract_list(tmp_path):
    labdir = tmp_path / "lab"
    assert grok_command(labdir, "grok-4.7", "medium") == [
        "grok",
        "--prompt-file", str(labdir / "prompt.txt"),
        "--always-approve",
        "--output-format", "plain",
        "-m", "grok-4.7",
        "--effort", "medium",
        "--cwd", str(labdir),
        "--sandbox", "workspace",
        "--no-subagents",
        "--deny", "Bash(git push*)",
        "--deny", "Bash(sudo*)",
        "--deny", "Bash(rm -rf /*)",
        "--deny", "mcp__*",
    ]


def test_sandbox_env_keeps_the_whitelist_and_extras(tmp_path):
    del tmp_path
    source = {
        "PATH": "/bin",
        "HOME": "/h",
        "LANG": "C",
        "LC_ALL": "C",
        "TERM": "xterm",
        "TMPDIR": "/t",
        "FOO": "1",
        "EDITOR": "vi",
    }
    cleaned = sandbox_env(source, extra=("FOO",))
    assert cleaned == {
        "PATH": "/bin",
        "HOME": "/h",
        "LANG": "C",
        "LC_ALL": "C",
        "TERM": "xterm",
        "TMPDIR": "/t",
        "FOO": "1",
    }


@pytest.mark.parametrize(
    "name",
    ["TOKEN", "API_KEY", "SECRET", "PASSWORD", "AUTH", "X_TOKEN_Y", "aws_secret", "MONKEY"],
)
def test_secret_names_never_pass_even_on_the_whitelist(name):
    cleaned = sandbox_env({"PATH": "/bin", name: "no"}, extra=(name, "PATH"))
    assert name not in cleaned
    assert cleaned == {"PATH": "/bin"}


def test_yaml_lab_budget_overrides_the_defaults(tmp_path):
    path = tmp_path / "guild.yaml"
    path.write_text(
        "code_mode:\n  lab:\n    max_labs: {T2: 1, T3: 2}\n    max_replans: 0\n    timeout_per_lab: 15m\n",
        encoding="utf-8",
    )
    config = load_code_mode_config(path)
    assert config.lab_max_t2 == 1
    assert config.lab_max_t3 == 2
    assert config.lab_max_replans == 0
    assert config.lab_timeout_s == 900


@pytest.mark.parametrize(
    ("stdout", "marker", "expected"),
    [
        (lab_line(APPROVE), "LAB_RESULT:", APPROVE),
        ("ruido\n" + lab_line(APPROVE) + "\n", "LAB_RESULT:", APPROVE),
        ("sin bloque", "LAB_RESULT:", None),
        (lab_line({**APPROVE, "verdict": "TALVEZ"}), "LAB_RESULT:", None),
        (lab_line({**APPROVE, "evidence_class": "humo"}), "LAB_RESULT:", None),
        ("LAB_RESULT: {", "LAB_RESULT:", None),
    ],
)
def test_parse_marked_block(stdout, marker, expected):
    assert parse_marked_block(stdout, marker) == expected


def test_approve_parses_lab_evidence_and_does_not_use_a_shell(tmp_path, monkeypatch):
    seen = {}
    import subprocess

    real = subprocess.Popen

    def spy(*args, **kwargs):
        seen["args"] = args
        seen["shell"] = kwargs.get("shell", False)
        seen["env"] = kwargs.get("env")
        return real(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", spy)
    monkeypatch.setenv("PHASE2_TOKEN", "nope")
    script = tmp_path / "fake.py"
    script.write_text(
        "import json, os\n"
        "from pathlib import Path\n"
        "Path('seen-env.json').write_text(json.dumps(sorted(os.environ)))\n"
        f"print({lab_line(APPROVE)!r})\n",
        encoding="utf-8",
    )
    jobs = JobRunner(tmp_path / "jobs", FakeClock(T0))
    lab = runner(
        tmp_path,
        jobs,
        command_for=lambda route, labdir, kind: [sys.executable, str(script)],
        timeout_s=5,
        environ={
            "PATH": "/usr/bin",
            "HOME": "/tmp",
            "LANG": "C",
            "PHASE2_TOKEN": "nope",
            "FOO": "1",
            "AWS_SECRET_ACCESS_KEY": "no",
        },
        env_extra=("FOO", "AWS_SECRET_ACCESS_KEY", "PHASE2_TOKEN"),
    )
    outcomes = lab.run_hypothesis(
        project_id="P-1",
        slug="Transcribir",
        tier="T2",
        hypothesis="el audio entra en menos de un minuto",
    )
    assert len(outcomes) == 1
    item = outcomes[0]
    assert item.launched is True
    assert item.untested_reason is None
    evidence = item.evidence
    assert evidence.verdict == "APPROVE"
    assert evidence.evidence_class == "running"
    assert evidence.timed_out is False
    assert evidence.hypothesis == "el audio entra en menos de un minuto"
    assert evidence.commands == ("python probe.py",)
    assert evidence.result == "40 segundos"
    assert evidence.artifacts == ("probe.txt",)
    assert evidence.role == "lab-runner"
    assert evidence.project_id == "P-1"
    assert evidence.lab_path.endswith("2026-10-20-transcribir-1")
    assert Path(evidence.lab_path).parent == tmp_path / "labs"
    prompt = (Path(evidence.lab_path) / "prompt.txt").read_text(encoding="utf-8")
    assert "Hipótesis: el audio entra en menos de un minuto" in prompt
    assert "LAB_RESULT:" in prompt
    seen_env = json.loads((Path(evidence.lab_path) / "seen-env.json").read_text(encoding="utf-8"))
    assert "PATH" in seen_env
    assert "FOO" in seen_env
    assert "PHASE2_TOKEN" not in seen_env
    assert "AWS_SECRET_ACCESS_KEY" not in seen_env
    assert seen["shell"] is False
    assert isinstance(seen["args"][0], list)
    assert seen["args"][0][0] == sys.executable


def test_invalid_block_is_inconclusive_paper(tmp_path):
    jobs = ScriptedJobs([("solo texto", False)])
    lab = runner(tmp_path, jobs)
    item = lab.run_hypothesis(project_id="P-1", slug="eco", tier="T2", hypothesis="entra")[0]
    assert item.launched is True
    assert item.evidence.verdict == "INCONCLUSIVE"
    assert item.evidence.evidence_class == "paper"
    assert item.evidence.timed_out is False
    assert item.evidence.result == "solo texto"
    assert item.evidence.hypothesis == "entra"


def test_timeout_keeps_partial_output(tmp_path):
    jobs = JobRunner(tmp_path / "jobs", FakeClock(T0))
    script = "import time; print('parcial', flush=True); time.sleep(30)"
    lab = runner(
        tmp_path,
        jobs,
        timeout_s=0.4,
        command_for=lambda route, labdir, kind: [sys.executable, "-c", script],
    )
    item = lab.run_hypothesis(project_id="P-1", slug="lento", tier="T2", hypothesis="tarda")[0]
    assert item.launched is True
    assert item.evidence.timed_out is True
    assert item.evidence.verdict == "INCONCLUSIVE"
    assert item.evidence.evidence_class == "paper"
    assert "parcial" in item.evidence.result


def test_security_fail_does_not_launch(tmp_path):
    jobs = ScriptedJobs([("no", False)])
    lab = runner(
        tmp_path,
        jobs,
        command_for=lambda route, labdir, kind: ["git", "push", "--force"],
    )
    item = lab.run_hypothesis(project_id="P-1", slug="peligro", tier="T2", hypothesis="rompe")[0]
    assert item.launched is False
    assert item.evidence is None
    assert item.untested_reason == "sin probar: destructive_cmd"
    assert jobs.calls == []


@pytest.mark.parametrize("verdict", ["INCONCLUSIVE", "YIELD", "REVISE", "APPROVE"])
def test_only_a_reject_opens_another_lab(tmp_path, verdict):
    payload = {**APPROVE, "verdict": verdict, "evidence_class": "paper" if verdict != "APPROVE" else "running"}
    jobs = ScriptedJobs([(lab_line(payload), False), (lab_line(APPROVE), False)])
    lab = runner(tmp_path, jobs, max_replans=1, max_labs_t2=3)
    outcomes = lab.run_hypothesis(project_id="P-1", slug="eco", tier="T2", hypothesis="entra")
    assert len(jobs.calls) == 1
    assert len(outcomes) == 1
    assert outcomes[0].evidence.verdict == verdict


def test_reject_replans_once_inside_the_budget(tmp_path):
    rejected = {**APPROVE, "verdict": "REJECT", "evidence_class": "running", "result": "no entra"}
    jobs = ScriptedJobs(
        [
            (lab_line(rejected), False),
            (lab_line(rejected), False),
            (lab_line(APPROVE), False),
        ]
    )
    lab = runner(tmp_path, jobs, max_replans=1, max_labs_t2=3)
    outcomes = lab.run_hypothesis(project_id="P-1", slug="eco", tier="T2", hypothesis="entra")
    assert [item.evidence.verdict for item in outcomes] == ["REJECT", "REJECT"]
    assert [Path(item.evidence.lab_path).name for item in outcomes] == [
        "2026-10-20-eco-1",
        "2026-10-20-eco-2",
    ]
    assert len(jobs.calls) == 2


def test_reject_stops_at_the_lab_cap(tmp_path):
    rejected = {**APPROVE, "verdict": "REJECT", "evidence_class": "running"}
    jobs = ScriptedJobs([(lab_line(rejected), False) for _ in range(5)])
    lab = runner(tmp_path, jobs, max_replans=5, max_labs_t3=2)
    outcomes = lab.run_hypothesis(project_id="P-1", slug="eco", tier="T3", hypothesis="entra")
    assert len(outcomes) == 2
    assert len(jobs.calls) == 2


def test_reject_then_approve_uses_the_replan(tmp_path):
    rejected = {**APPROVE, "verdict": "REJECT", "evidence_class": "running"}
    jobs = ScriptedJobs([(lab_line(rejected), False), (lab_line(APPROVE), False)])
    lab = runner(tmp_path, jobs, max_replans=1, max_labs_t2=3)
    outcomes = lab.run_hypothesis(project_id="P-1", slug="eco", tier="T2", hypothesis="entra")
    assert [item.evidence.verdict for item in outcomes] == ["REJECT", "APPROVE"]


def test_maverick_parses_one_call(tmp_path):
    payload = {
        "alternatives": [
            {
                "name": "local",
                "idea": "correr en la máquina",
                "pros": "sin cuenta",
                "cons": "más lento",
                "cost": "bajo",
                "verdict": "YIELD",
            }
        ],
        "recommendation": "probar local primero",
    }
    jobs = ScriptedJobs([(mav_line(payload), False)])
    lab = runner(tmp_path, jobs, maverick_timeout_s=300)
    text = lab.consult_maverick(project_id="P-1", slug="eco", context="transcribir un video")
    assert len(jobs.calls) == 1
    assert jobs.calls[0]["timeout_s"] == 300
    assert "MAVERICK_RESULT:" in jobs.calls[0]["prompt"]
    assert "transcribir un video" in jobs.calls[0]["prompt"]
    assert text == (
        "CONSULT: propone, no decide.\n"
        "- local: correr en la máquina | a favor: sin cuenta | en contra: más lento | costo: bajo | YIELD\n"
        "Recomendación: probar local primero"
    )


def test_maverick_timeout_is_a_missing_consult(tmp_path):
    jobs = ScriptedJobs([("parcial", True)])
    lab = runner(tmp_path, jobs)
    assert lab.consult_maverick(project_id="P-1", slug="eco", context="x") == "sin consulta: timeout"
    assert len(jobs.calls) == 1


def test_maverick_without_a_block_is_a_missing_consult(tmp_path):
    jobs = ScriptedJobs([("hola", False)])
    lab = runner(tmp_path, jobs)
    assert lab.consult_maverick(project_id="P-1", slug="eco", context="x") == "sin consulta: sin bloque"


def test_maverick_error_is_a_missing_consult(tmp_path):
    jobs = ScriptedJobs([RuntimeError("boom")])
    lab = runner(tmp_path, jobs)
    assert lab.consult_maverick(project_id="P-1", slug="eco", context="x") == "sin consulta: error"


def test_runner_defaults_are_fifteen_and_five_minutes(tmp_path):
    jobs = ScriptedJobs([])
    lab = LabRunner(clock=FakeClock(T0), lab_root=tmp_path / "labs", jobs=jobs)
    assert lab.timeout_s == 900
    assert lab.maverick_timeout_s == 300
    assert lab.max_labs_t2 == 2
    assert lab.max_labs_t3 == 3
    assert lab.max_replans == 1

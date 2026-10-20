"""El entrypoint acepta las opciones del lab sin invocar un CLI real."""

from pathlib import Path

from universal_bot.labcode_runtime import main

DEFAULT_ROOT = Path("/tmp/ub-labcode")


def _run(argv):
    try:
        return main(argv)
    except SystemExit as exc:
        return exc.code


def _spy(monkeypatch):
    seen = {}

    class Spy:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    monkeypatch.setattr("universal_bot.code_mode.lab_runner.LabRunner", Spy)
    return seen


def test_cli_flags_configure_the_lab(tmp_path, monkeypatch):
    seen = _spy(monkeypatch)
    root = tmp_path / "labs"
    policy = tmp_path / "routing.yaml"
    code = _run(
        [
            "--spool",
            str(tmp_path / "spool"),
            "--once",
            "--db",
            str(tmp_path / "mode.sqlite"),
            "--lab-root",
            str(root),
            "--routing-policy",
            str(policy),
            "--lab-timeout",
            "90",
            "--maverick-timeout",
            "30",
            "--max-labs",
            "1",
        ]
    )
    assert code == 0
    assert seen["lab_root"] == root
    assert seen["routing_policy"] == policy
    assert seen["timeout_s"] == 90.0
    assert seen["maverick_timeout_s"] == 30.0
    assert seen["max_labs_t2"] == 1
    assert seen["max_labs_t3"] == 1


def test_cli_lab_defaults_when_flags_are_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("UBLAB_CONFIG", "")
    monkeypatch.delenv("UBLAB_ROUTING_POLICY", raising=False)
    monkeypatch.delenv("UBLAB_LAB_ROOT", raising=False)
    seen = _spy(monkeypatch)
    code = _run(
        [
            "--spool",
            str(tmp_path / "spool"),
            "--once",
            "--db",
            str(tmp_path / "mode.sqlite"),
        ]
    )
    assert code == 0
    assert seen.get("lab_root") == DEFAULT_ROOT
    assert seen.get("routing_policy") == Path()
    assert seen.get("timeout_s") == 900.0
    assert seen.get("maverick_timeout_s") == 300.0
    assert seen.get("max_labs_t2") == 2
    assert seen.get("max_labs_t3") == 3

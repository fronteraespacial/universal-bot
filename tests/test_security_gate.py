"""Gate de seguridad del sandbox: violaciones concretas y PASS sin pregunta."""

from datetime import datetime, timezone

import pytest

from universal_bot.code_mode.config import ConfigError
from universal_bot.code_mode.security_gate import (
    SandboxInspection,
    evaluate,
    validate_security_config,
)

T0 = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
ALLOW = ("pypi.org", "files.pythonhosted.org", "github.com")


def inspection(**overrides) -> SandboxInspection:
    payload = {
        "env": (("PATH", "/usr/bin"),),
        "commands": ("pytest -q",),
        "write_paths": ("/work/app/src/a.py",),
        "hosts": ("pypi.org",),
        "workspace": "/work/app",
        "real_service": False,
        "encapsulable": True,
    }
    payload.update(overrides)
    return SandboxInspection(**payload)


def check(item: SandboxInspection, **overrides):
    payload = {
        "project_id": "P-1",
        "sandbox_id": "sb",
        "checked_at": T0,
        "allowlist": ALLOW,
        "security_check": "on",
        "host_role": "vps",
    }
    payload.update(overrides)
    return evaluate(item, **payload)


def test_clean_sandbox_passes_without_asking():
    decision = check(inspection())
    assert decision.result.passed is True
    assert decision.result.encapsulable is True
    assert decision.result.violations == ()
    assert decision.result.project_id == "P-1"
    assert decision.result.sandbox_id == "sb"
    assert decision.result.checked_at == T0
    assert decision.tests_allowed is True
    assert decision.ask is False


@pytest.mark.parametrize(
    "name",
    [
        "PROD_SECRET",
        "PROD_TOKEN",
        "PROD_KEY",
        "PROD_PASSWORD",
        "PRODUCTION_SECRET",
        "SECRET_PROD",
        "TOKEN_PROD",
        "API_PROD_SECRET",
    ],
)
def test_prod_secret_fails_and_blocks_tests(name):
    decision = check(inspection(env=((name, "abc"),)))
    assert decision.result.passed is False
    assert decision.result.violations == ("prod_secret",)
    assert decision.tests_allowed is False
    assert decision.ask is True


def test_benign_env_names_pass():
    decision = check(inspection(env=(("PATH", "/usr/bin"), ("PROD_MODE", "1"), ("HOME", "/home/app"))))
    assert decision.result.passed is True
    assert decision.result.violations == ()


def test_host_outside_allowlist_fails():
    decision = check(inspection(hosts=("pypi.org", "evil.example")))
    assert decision.result.violations == ("external_host",)
    assert decision.tests_allowed is False
    assert decision.ask is True


@pytest.mark.parametrize("path", ["/etc/passwd", "/work/app-evil/x"])
def test_write_outside_workspace_fails(path):
    decision = check(inspection(write_paths=(path,)))
    assert decision.result.violations == ("write_outside_workspace",)
    assert decision.tests_allowed is False


def test_relative_write_inside_workspace_passes():
    decision = check(inspection(write_paths=("/work/app/src/a.py", "rel.txt")))
    assert decision.result.passed is True
    assert decision.result.violations == ()


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /",
        "git push --force",
        "git push --force origin main",
        "git push -f origin main",
        "DROP TABLE users",
        "drop table users",
    ],
)
def test_destructive_command_fails(command):
    decision = check(inspection(commands=(command,)))
    assert decision.result.violations == ("destructive_cmd",)
    assert decision.tests_allowed is False
    assert decision.ask is True


def test_real_service_access_fails():
    decision = check(inspection(real_service=True))
    assert decision.result.violations == ("real_service_access",)
    assert decision.tests_allowed is False
    assert decision.ask is True


def test_not_encapsulable_asks_without_a_violation():
    decision = check(inspection(encapsulable=False))
    assert decision.result.passed is False
    assert decision.result.encapsulable is False
    assert decision.result.violations == ()
    assert decision.ask is True
    assert decision.tests_allowed is False


def test_violations_keep_a_stable_order():
    decision = check(
        inspection(
            env=(("PROD_SECRET", "x"),),
            hosts=("evil.example",),
            write_paths=("/etc/passwd",),
            commands=("rm -rf /",),
            real_service=True,
        )
    )
    assert decision.result.violations == (
        "prod_secret",
        "external_host",
        "write_outside_workspace",
        "destructive_cmd",
        "real_service_access",
    )


def test_security_check_off_on_a_shared_server_is_a_config_error():
    with pytest.raises(ConfigError, match="servidor compartido"):
        validate_security_config("off", "vps")


def test_security_check_off_on_local_is_allowed():
    validate_security_config("off", "local")


def test_evaluate_refuses_to_run_when_the_check_is_off_on_a_shared_server():
    with pytest.raises(ConfigError, match="servidor compartido"):
        check(inspection(), security_check="off", host_role="vps")

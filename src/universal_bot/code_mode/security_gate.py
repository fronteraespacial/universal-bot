"""Chequeo automático del sandbox antes de correr pruebas."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
import re

from universal_bot.code_mode.config import ConfigError
from universal_bot.code_mode.models import SecurityCheckResult

_PROD_SECRET = re.compile(
    r"(?i)(?:^|_)(?:prod|production)_(?:secret|token|key|password)$"
    r"|^(?:secret|token|key|password)_(?:prod|production)$"
    r"|(?:^|_)prod_(?:secret|token|key|password)$"
)
_DESTRUCTIVE = (
    re.compile(r"(?i)(?:^|\s)rm\s+-rf\s+/(?:\s|$)"),
    re.compile(r"(?i)\bgit\s+push\b.*(?:--force\b|(?:^|\s)-f(?:\s|$))"),
    re.compile(r"(?i)\bdrop\s+table\b"),
)


@dataclass(frozen=True)
class SandboxInspection:
    env: tuple[tuple[str, str], ...]
    commands: tuple[str, ...]
    write_paths: tuple[str, ...]
    hosts: tuple[str, ...]
    workspace: str
    real_service: bool = False
    encapsulable: bool = True


@dataclass(frozen=True)
class SecurityDecision:
    result: SecurityCheckResult
    tests_allowed: bool
    ask: bool


def validate_security_config(security_check: str, host_role: str) -> None:
    if security_check == "off" and host_role != "local":
        raise ConfigError("security_check off no se permite en un servidor compartido")


def evaluate(
    inspection: SandboxInspection,
    *,
    project_id: str,
    sandbox_id: str,
    checked_at: datetime,
    allowlist: tuple[str, ...],
    security_check: str = "on",
    host_role: str = "vps",
) -> SecurityDecision:
    validate_security_config(security_check, host_role)
    violations: list[str] = []
    if _has_prod_secret(inspection.env):
        violations.append("prod_secret")
    if _has_external_host(inspection.hosts, allowlist):
        violations.append("external_host")
    if _writes_outside(inspection.write_paths, inspection.workspace):
        violations.append("write_outside_workspace")
    if _has_destructive(inspection.commands):
        violations.append("destructive_cmd")
    if inspection.real_service:
        violations.append("real_service_access")
    passed = inspection.encapsulable and not violations
    result = SecurityCheckResult(
        project_id=project_id,
        sandbox_id=sandbox_id,
        checked_at=checked_at,
        passed=passed,
        encapsulable=inspection.encapsulable,
        violations=tuple(violations),
        detail_ref=None,
    )
    return SecurityDecision(result, tests_allowed=passed, ask=not passed)


def _has_prod_secret(env: tuple[tuple[str, str], ...]) -> bool:
    return any(_PROD_SECRET.search(name) for name, _value in env)


def _has_external_host(hosts: tuple[str, ...], allowlist: tuple[str, ...]) -> bool:
    allowed = set(allowlist)
    return any(host not in allowed for host in hosts)


def _writes_outside(paths: tuple[str, ...], workspace: str) -> bool:
    root = PurePosixPath(workspace)
    for raw in paths:
        path = PurePosixPath(raw)
        if not path.is_absolute():
            path = root / path
        try:
            path.relative_to(root)
        except ValueError:
            return True
    return False


def _has_destructive(commands: tuple[str, ...]) -> bool:
    return any(pattern.search(command) for command in commands for pattern in _DESTRUCTIVE)

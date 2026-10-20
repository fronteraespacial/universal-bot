"""Configuración del modo código. Defaults del diseño §6."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
import re

import yaml

_DURATION = re.compile(r"^(\d+)([mhd])$")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class RolePolicy:
    can_start_project: tuple[str, ...] = ("@dev", "@admin")
    can_start_thread: tuple[str, ...] = ("@everyone",)
    can_activate: tuple[str, ...] = ("@dev", "@admin")
    can_ask_questions: tuple[str, ...] = ("requester", "@dev")
    can_brake: tuple[str, ...] = ("requester", "@admin")
    admin_review_channel: str = "admin-bot"


@dataclass(frozen=True)
class ApprovalPolicy:
    production: str = "requester|dev"
    production_t3: str = "dev"
    dev_roles: tuple[str, ...] = ("@dev",)
    plan: str = "none"
    plan_requires_evidence: bool = True


@dataclass(frozen=True)
class SandboxPolicy:
    policy: str = "strict"
    runtime: str = "worktree+venv"
    egress_allowlist: tuple[str, ...] = ("pypi.org", "files.pythonhosted.org", "github.com")
    prod_secrets: str = "deny"
    writes: str = "workspace_only"


@dataclass(frozen=True)
class CodeModeConfig:
    enabled: bool = True
    propose_tiers: tuple[str, ...] = ("T2", "T3")
    default_mode: str = "ask"
    sticky: bool = True
    default_duration: str = "4h"
    duration_options: tuple[str, ...] = ("1h", "4h", "until_exit")
    warn_before: str = "10m"
    proposal_threshold: float = 0.8
    who_can_exit: tuple[str, ...] = ("activator", "@dev", "@admin")
    manual_trigger_phrases: tuple[str, ...] = (
        "pasemos a modo código",
        "modo programación",
        "activá modo código",
    )
    manual_trigger_command: str = "/modo-codigo"
    trivial_to_basic_cli: bool = True
    allow_channels: bool = True
    projects_category: str = "Proyectos"
    projects_channel: str = "proyectos"
    channel_prefix: str = "p-"
    max_open_projects: int = 10
    archive_after_days: int = 14
    roles: RolePolicy = RolePolicy()
    approvals: ApprovalPolicy = ApprovalPolicy()
    sandbox: SandboxPolicy = SandboxPolicy()
    security_check: str = "on"
    host_role: str = "vps"
    allowed_channels: tuple[int, ...] = (1562169649574051942,)
    reminders_first_after: str = "4h"
    reminders_pause_after: str = "24h"
    reminders_cancel_paused_after: str = "7d"
    language_user: str = "es-AR-simple"
    language_stages: str = "es-AR-tecnico"
    lab_max_t2: int = 2
    lab_max_t3: int = 3
    lab_max_replans: int = 1
    lab_timeout_s: float = 900.0
    maverick_timeout_s: float = 300.0
    lab_root: str = ""
    routing_policy: str = "/workspace/codemode-base/catalog/routing-policy.yaml"
    env_extra: tuple[str, ...] = ()
    role_map: tuple[tuple[str, tuple[str, ...]], ...] | None = None


def parse_duration(spec: str) -> timedelta | None:
    if spec == "until_exit":
        return None
    match = _DURATION.fullmatch(spec)
    if match is None:
        raise ValueError(f"duración desconocida: {spec}")
    amount = int(match.group(1))
    unit = match.group(2)
    if unit == "m":
        return timedelta(minutes=amount)
    if unit == "h":
        return timedelta(hours=amount)
    return timedelta(days=amount)


def role_allowed(
    specs: tuple[str, ...],
    actor_roles: tuple[str, ...],
    *,
    actor_id: int | None = None,
    requester_id: int | None = None,
    activator_id: int | None = None,
) -> bool:
    if "@everyone" in specs:
        return True
    roles = set(actor_roles)
    for spec in specs:
        if spec == "activator" and actor_id is not None and actor_id == activator_id:
            return True
        if spec == "requester" and actor_id is not None and actor_id == requester_id:
            return True
        if spec in roles:
            return True
    return False


_TIERS = {"T0", "T1", "T2", "T3"}
_PRODUCTION = {"requester", "dev", "requester|dev"}


def load_code_mode_config(path) -> CodeModeConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError("el yaml tiene que ser un mapa")
    block = raw.get("code_mode") if "code_mode" in raw else raw
    if block is None:
        block = {}
    if not isinstance(block, dict):
        raise ConfigError("code_mode tiene que ser un mapa")
    base = CodeModeConfig()
    threshold = _threshold(block.get("proposal_threshold", base.proposal_threshold))
    approvals = _approvals(block.get("approvals"), base.approvals)
    security_check = _on_off(block["security_check"]) if "security_check" in block else base.security_check
    host_role = str(block.get("host_role", base.host_role))
    validate_security_config(security_check, host_role)
    reminders = block.get("reminders") or {}
    language = block.get("language") or {}
    return replace(
        base,
        enabled=_flag(block, "enabled", base.enabled),
        propose_tiers=_tiers(block.get("propose_tiers", base.propose_tiers)),
        default_mode=str(block.get("default_mode", base.default_mode)),
        sticky=_flag(block, "sticky", base.sticky),
        default_duration=str(block.get("default_duration", base.default_duration)),
        duration_options=_strings(block.get("duration_options", base.duration_options), "duration_options"),
        warn_before=str(block.get("warn_before", base.warn_before)),
        proposal_threshold=threshold,
        who_can_exit=_strings(block.get("who_can_exit", base.who_can_exit), "who_can_exit"),
        manual_trigger_phrases=_strings(
            block.get("manual_trigger_phrases", base.manual_trigger_phrases),
            "manual_trigger_phrases",
        ),
        manual_trigger_command=str(block.get("manual_trigger_command", base.manual_trigger_command)),
        trivial_to_basic_cli=_flag(block, "trivial_to_basic_cli", base.trivial_to_basic_cli),
        allow_channels=_flag(block, "allow_channels", base.allow_channels),
        projects_category=str(block.get("projects_category", base.projects_category)),
        projects_channel=str(block.get("projects_channel", base.projects_channel)),
        channel_prefix=str(block.get("channel_prefix", base.channel_prefix)),
        max_open_projects=int(block.get("max_open_projects", base.max_open_projects)),
        archive_after_days=int(block.get("archive_after_days", base.archive_after_days)),
        roles=_roles(block.get("roles"), base.roles),
        approvals=approvals,
        sandbox=_sandbox(block.get("sandbox"), base.sandbox),
        security_check=security_check,
        host_role=host_role,
        allowed_channels=_channels(block.get("allowed_channels", base.allowed_channels)),
        reminders_first_after=str(reminders.get("first_after", base.reminders_first_after)),
        reminders_pause_after=str(reminders.get("pause_after", base.reminders_pause_after)),
        reminders_cancel_paused_after=str(
            reminders.get("cancel_paused_after", base.reminders_cancel_paused_after)
        ),
        language_user=str(language.get("user", base.language_user)),
        language_stages=str(language.get("stages", base.language_stages)),
        role_map=_role_map(block["role_map"]) if "role_map" in block else base.role_map,
        **_lab_fields(block.get("lab"), base),
    )


def validate_security_config(security_check: str, host_role: str) -> None:
    if security_check == "off" and host_role != "local":
        raise ConfigError("security_check off no se permite en un servidor compartido")


def _on_off(value: object) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    text = str(value).strip().lower()
    if text in {"on", "true", "yes", "1"}:
        return "on"
    if text in {"off", "false", "no", "0"}:
        return "off"
    raise ConfigError("security_check tiene que ser on u off")


def _flag(block: dict, key: str, default: bool) -> bool:
    if key not in block:
        return default
    value = block[key]
    if not isinstance(value, bool):
        raise ConfigError(f"{key} tiene que ser sí o no")
    return value


def _threshold(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= float(value) <= 1:
        raise ConfigError("proposal_threshold tiene que estar entre 0 y 1")
    return float(value)


def _tiers(value: object) -> tuple[str, ...]:
    items = _strings(value, "propose_tiers")
    unknown = [item for item in items if item not in _TIERS]
    if unknown:
        raise ConfigError(f"propose_tiers desconocido: {unknown[0]}")
    return items


def _strings(value: object, field: str) -> tuple[str, ...]:
    if isinstance(value, tuple):
        return tuple(str(item) for item in value)
    if not isinstance(value, list):
        raise ConfigError(f"{field} tiene que ser una lista")
    return tuple(str(item) for item in value)


def _channels(value: object) -> tuple[int, ...]:
    if isinstance(value, tuple):
        items = list(value)
    elif isinstance(value, list):
        items = value
    else:
        raise ConfigError("allowed_channels tiene que ser una lista")
    channels: list[int] = []
    for item in items:
        if isinstance(item, bool) or not isinstance(item, int):
            raise ConfigError("allowed_channels tiene que ser numérico")
        channels.append(item)
    return tuple(channels)


def _roles(value: object, base: RolePolicy) -> RolePolicy:
    if value is None:
        return base
    if not isinstance(value, dict):
        raise ConfigError("roles tiene que ser un mapa")
    return replace(
        base,
        can_start_project=_strings(value.get("can_start_project", base.can_start_project), "can_start_project"),
        can_start_thread=_strings(value.get("can_start_thread", base.can_start_thread), "can_start_thread"),
        can_activate=_strings(value.get("can_activate", base.can_activate), "can_activate"),
        can_ask_questions=_strings(value.get("can_ask_questions", base.can_ask_questions), "can_ask_questions"),
        can_brake=_strings(value.get("can_brake", base.can_brake), "can_brake"),
        admin_review_channel=str(value.get("admin_review_channel", base.admin_review_channel)),
    )


def _approvals(value: object, base: ApprovalPolicy) -> ApprovalPolicy:
    if value is None:
        return base
    if not isinstance(value, dict):
        raise ConfigError("approvals tiene que ser un mapa")
    production = str(value.get("production", base.production))
    if production not in _PRODUCTION:
        raise ConfigError("approvals.production tiene que ser requester, dev o requester|dev")
    return replace(
        base,
        production=production,
        production_t3=str(value.get("production_t3", base.production_t3)),
        dev_roles=_strings(value.get("dev_roles", base.dev_roles), "dev_roles"),
        plan=str(value.get("plan", base.plan)),
        plan_requires_evidence=bool(value.get("plan_requires_evidence", base.plan_requires_evidence)),
    )


def _lab_fields(value: object, base: CodeModeConfig) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError("lab tiene que ser un mapa")
    max_labs = value.get("max_labs") or {}
    if not isinstance(max_labs, dict):
        raise ConfigError("lab.max_labs tiene que ser un mapa")
    timeout = base.lab_timeout_s
    if "timeout_per_lab" in value:
        delta = parse_duration(str(value["timeout_per_lab"]))
        if delta is None:
            raise ConfigError("timeout_per_lab tiene que ser una duración")
        timeout = delta.total_seconds()
    maverick = base.maverick_timeout_s
    if "maverick_timeout_s" in value:
        maverick = float(value["maverick_timeout_s"])
    extra = value.get("env_extra", base.env_extra)
    return {
        "lab_max_t2": int(max_labs.get("T2", base.lab_max_t2)),
        "lab_max_t3": int(max_labs.get("T3", base.lab_max_t3)),
        "lab_max_replans": int(value.get("max_replans", base.lab_max_replans)),
        "lab_timeout_s": float(timeout),
        "maverick_timeout_s": float(maverick),
        "lab_root": str(value.get("lab_root", base.lab_root)),
        "routing_policy": str(value.get("routing_policy", base.routing_policy)),
        "env_extra": _strings(extra, "env_extra") if not isinstance(extra, tuple) else tuple(extra),
    }


def _role_map(value: object) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if not isinstance(value, dict):
        raise ConfigError("role_map tiene que ser un mapa")
    rows = []
    for key, roles in value.items():
        rows.append((str(key), _strings(roles, "role_map")))
    return tuple(rows)


def _sandbox(value: object, base: SandboxPolicy) -> SandboxPolicy:
    if value is None:
        return base
    if not isinstance(value, dict):
        raise ConfigError("sandbox tiene que ser un mapa")
    return replace(
        base,
        policy=str(value.get("policy", base.policy)),
        runtime=str(value.get("runtime", base.runtime)),
        egress_allowlist=_strings(value.get("egress_allowlist", base.egress_allowlist), "egress_allowlist"),
        prod_secrets=str(value.get("prod_secrets", base.prod_secrets)),
        writes=str(value.get("writes", base.writes)),
    )



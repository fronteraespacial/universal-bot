"""Configuración del modo código. Defaults del diseño §6."""

from __future__ import annotations

from dataclasses import dataclass


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



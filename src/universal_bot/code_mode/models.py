"""Contratos del modo código. Datos frozen, sin comportamiento."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class ProjectMode(str, Enum):
    CHANNEL = "channel"
    THREAD = "thread"


class ProjectState(str, Enum):
    PROPOSED = "PROPOSED"
    PENDING_ADMIN = "PENDING_ADMIN"
    PROVISIONING = "PROVISIONING"
    SANDBOX_CHECK = "SANDBOX_CHECK"
    LAB_RUNNING = "LAB_RUNNING"
    PLAN_READY = "PLAN_READY"
    RUNNING = "RUNNING"
    WAITING_HUMAN = "WAITING_HUMAN"
    PENDING_PROD_APPROVAL = "PENDING_PROD_APPROVAL"
    DEPLOYING = "DEPLOYING"
    PAUSED = "PAUSED"
    ESCALATED = "ESCALATED"
    DONE = "DONE"
    CANCELLED = "CANCELLED"
    DECLINED = "DECLINED"
    ARCHIVED = "ARCHIVED"


class SessionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    EXITED = "EXITED"


class ActivationKind(str, Enum):
    PROPOSAL_HERE = "proposal_here"
    PROJECT_CHANNEL = "project_channel"
    PROJECT_THREAD = "project_thread"
    MANUAL_PHRASE = "manual_phrase"
    COMMAND = "command"
    BUTTON = "button"


class Violation(str, Enum):
    PROD_SECRET = "prod_secret"
    EXTERNAL_HOST = "external_host"
    WRITE_OUTSIDE_WORKSPACE = "write_outside_workspace"
    DESTRUCTIVE_CMD = "destructive_cmd"
    REAL_SERVICE_ACCESS = "real_service_access"


class QuestionKind(str, Enum):
    CODE_MODE_PROPOSAL = "code_mode_proposal"
    PROD_APPROVAL = "prod_approval"
    SANDBOX_CHECK_FAILED = "sandbox_check_failed"
    LAB_INCONCLUSIVE = "lab_inconclusive"
    ADVISOR_CARD = "advisor_card"
    HUMAN_BRAKE = "human_brake"
    ADMIN_PROVISION = "admin_provision"
    BRIEF_CONFIRM = "brief_confirm"


BLOCKING_QUESTION_KINDS = frozenset(
    {
        QuestionKind.PROD_APPROVAL,
        QuestionKind.SANDBOX_CHECK_FAILED,
        QuestionKind.ADMIN_PROVISION,
    }
)


class ProductionKind(str, Enum):
    DEPLOY = "deploy"
    MERGE_PROD_BRANCH = "merge_prod_branch"
    ENV_CHANGE = "env_change"
    DISCORD_IRREVERSIBLE = "discord_irreversible"
    SERVER_IRREVERSIBLE = "server_irreversible"


class EvidenceVerdict(str, Enum):
    APPROVE = "APPROVE"
    REVISE = "REVISE"
    REJECT = "REJECT"
    YIELD = "YIELD"
    INCONCLUSIVE = "INCONCLUSIVE"


class EvidenceClass(str, Enum):
    RUNNING = "running"
    PAPER = "paper"


@dataclass(frozen=True)
class Location:
    guild_id: int
    channel_id: int
    thread_id: int | None = None


@dataclass(frozen=True)
class SecurityCheckResult:
    project_id: str
    sandbox_id: str
    checked_at: datetime
    passed: bool
    encapsulable: bool
    violations: tuple[str, ...]
    detail_ref: str | None


@dataclass(frozen=True)
class Project:
    id: str
    guild_id: int
    requester_id: int
    origin_message_id: int
    slug: str
    title_plain: str
    tier: str
    work_type: str
    mode: ProjectMode
    state: ProjectState
    channel_id: int | None
    root_thread_id: int | None
    run_id: str
    wave: str
    sandbox_id: str | None
    last_security_check: SecurityCheckResult | None
    requires_production: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class CodeModeSession:
    id: str
    guild_id: int
    channel_id: int
    thread_id: int | None
    activated_by: int
    activation: str
    since: datetime
    until: datetime | None
    warn_at: datetime | None
    project_id: str | None
    pinned_message_id: int | None
    status: str
    ended_by: int | None
    ended_at: datetime | None


@dataclass(frozen=True)
class Stage:
    project_id: str
    key: str
    thread_id: int | None
    status: str
    summary_plain: str
    last_job_id: str | None


@dataclass(frozen=True)
class PendingQuestion:
    id: str
    project_id: str
    stage_key: str
    kind: str
    blocking: bool
    prompt_plain: str
    detail_ref: str | None
    options: tuple[str, ...]
    allowed_approvers: tuple[int, ...]
    message_id: int | None
    asked_at: datetime
    remind_at: datetime
    pause_at: datetime
    answer: str | None
    answered_by: int | None
    answered_at: datetime | None
    resume_token: str


@dataclass(frozen=True)
class LabEvidence:
    id: str
    project_id: str
    lab_path: str
    role: str
    hypothesis: str
    commands: tuple[str, ...]
    result: str
    artifacts: tuple[str, ...]
    verdict: str
    evidence_class: str
    security_check_ref: str
    started_at: datetime
    finished_at: datetime
    timed_out: bool


@dataclass(frozen=True)
class PlanStep:
    id: str
    workstream: str
    summary: str
    paths: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    untested_reason: str | None


@dataclass(frozen=True)
class Plan:
    project_id: str
    wave: str
    steps: tuple[PlanStep, ...]
    lab_evidence: tuple[LabEvidence, ...]
    maverick_consult: str | None
    requires_production: bool


@dataclass(frozen=True)
class ProductionAction:
    project_id: str
    kind: str
    target: str
    summary_plain: str
    approved_by: int | None = None
    approved_at: datetime | None = None


@dataclass(frozen=True)
class ProjectCheckpoint:
    project_id: str
    resume_token: str
    created_at: datetime

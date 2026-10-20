"""Orquesta el modo código sobre los servicios. Los tests usan FakeDiscord."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys

from universal_bot.code_mode.clock import Clock
from universal_bot.code_mode.config import CodeModeConfig
from universal_bot.code_mode.discord_port import DiscordPort
from universal_bot.code_mode.job_runner import JobRunner
from universal_bot.code_mode.models import (
    LabEvidence,
    Location,
    Plan,
    PlanStep,
    ProductionAction,
    Project,
    ProjectMode,
    ProjectState,
)
from universal_bot.code_mode.plan_validator import publish_plan
from universal_bot.code_mode.prod_gate import approve, complete_without_production, request_production
from universal_bot.code_mode.project_machine import transition
from universal_bot.code_mode.project_provisioner import ProjectProvisioner
from universal_bot.code_mode.projects import ProjectLedger
from universal_bot.code_mode.proposer import Proposer
from universal_bot.code_mode.security_gate import SandboxInspection, evaluate
from universal_bot.code_mode.session_manager import SessionManager

FORBIDDEN = "No podés aprobar esto."


class CodeModeApp:
    def __init__(self, db_path, discord: DiscordPort, clock: Clock, config: CodeModeConfig):
        self.discord = discord
        self.clock = clock
        self.config = config
        self.proposer_calls = 0
        self.blocking_asks = 0
        self.trace: list[str] = []
        self.last_plan: Plan | None = None
        self.ledger = ProjectLedger(db_path, clock)
        self.sessions = SessionManager(db_path, clock, discord, config, self.ledger)
        self.proposer = Proposer(discord, self.sessions, config, clock)
        self.provisioner = ProjectProvisioner(discord, self.sessions, self.ledger, config, clock)
        self.jobs_root = Path(db_path).parent / "jobs"
        self.jobs = JobRunner(self.jobs_root, clock)
        self._requests: dict = {}
        self._actions: dict[str, ProductionAction] = {}

    def handle_text(self, location: Location, actor_id: int, roles: tuple[str, ...], text: str):
        return self.sessions.handle_text(location, actor_id, roles, text)

    def exit(self, location: Location, actor_id: int, roles: tuple[str, ...]):
        return self.sessions.exit(location, actor_id, roles)

    def handle_request(
        self,
        location: Location,
        actor_id: int,
        roles: tuple[str, ...],
        *,
        text: str,
        tier: str,
        confidence: float,
        request_id: str,
    ):
        if self.sessions.resolve(location) is not None:
            return self.sessions.route(location, text)
        self.proposer_calls += 1
        proposal = self.proposer.propose(request_id, tier, confidence, location, actor_id)
        self._requests[request_id] = {
            "location": location,
            "actor_id": actor_id,
            "roles": roles,
            "text": text,
            "tier": tier,
        }
        return proposal

    def choose(self, request_id: str, option: str, actor_id: int, roles: tuple[str, ...], *, deploy: bool = False):
        stored = self._requests[request_id]
        choice = self.proposer.choose(request_id, option, actor_id, roles)
        if choice.kind != "provision" or choice.mode is None:
            return choice
        result = self.provisioner.provision(
            guild_id=stored["location"].guild_id,
            actor_id=actor_id,
            actor_roles=roles,
            requester_id=actor_id,
            title=stored["text"],
            tier=stored["tier"],
            mode=ProjectMode(choice.mode),
            origin_channel_id=stored["location"].channel_id,
        )
        if result.project is None:
            return result
        return self._pipeline(result.project, deploy=deploy)

    def approve_production(self, project_id: str, user_id: int, roles: tuple[str, ...]):
        project = self.ledger.get_project(project_id)
        action = self._actions[project_id]
        decision = approve(project, action, user_id, roles, self.config.approvals, self.clock.now())
        if not decision.accepted:
            self.discord.reply_ephemeral(user_id, FORBIDDEN)
            return decision
        self._remember(decision.project)
        return replace(decision, project=self._move(decision.project, ProjectState.DONE))

    def project(self, project_id: str) -> Project | None:
        return self.ledger.get_project(project_id)

    def _pipeline(self, project: Project, *, deploy: bool) -> Project:
        project = self._move(project, ProjectState.SANDBOX_CHECK)
        inspection = SandboxInspection(
            env=(("PATH", "/usr/bin"), ("HOME", "/work")),
            commands=(f"{sys.executable} -c print",),
            write_paths=("/work/app/out.txt",),
            hosts=("pypi.org",),
            workspace="/work/app",
        )
        decision = evaluate(
            inspection,
            project_id=project.id,
            sandbox_id="sb-e2e",
            checked_at=self.clock.now(),
            allowlist=self.config.sandbox.egress_allowlist,
            security_check=self.config.security_check,
            host_role=self.config.host_role,
        )
        if not decision.tests_allowed:
            raise RuntimeError("el sandbox de la prueba no pasó")
        project = self._move(project, ProjectState.LAB_RUNNING)
        evidence = self._evidence(project)
        plan = Plan(
            project_id=project.id,
            wave="O1",
            steps=(
                PlanStep(
                    id="S1",
                    workstream="api",
                    summary="publicar el slug",
                    paths=("src/slug.py",),
                    evidence_refs=(evidence.id,),
                    untested_reason=None,
                ),
            ),
            lab_evidence=(evidence,),
            maverick_consult="CONSULT: sin cambios",
            requires_production=deploy,
        )
        self.last_plan = plan
        published = publish_plan(
            project,
            plan,
            lab_was_running=True,
            open_questions=(),
            now=self.clock.now(),
        )
        transition(project.state, ProjectState.PLAN_READY)
        project = self._remember(published.project)
        project = self._move(project, ProjectState.RUNNING)
        if not deploy:
            transition(project.state, ProjectState.DONE)
            return self._remember(complete_without_production(project, self.clock.now()))
        transition(project.state, ProjectState.PENDING_PROD_APPROVAL)
        action = ProductionAction(project.id, "deploy", "prod", "pase a producción")
        project, action = request_production(project, action, self.clock.now())
        self._actions[project.id] = action
        return self._remember(project)

    def _evidence(self, project: Project) -> LabEvidence:
        command = [sys.executable, "-c", "print('lab-ok')"]
        run = self.jobs.run(
            slug="lab",
            command=command,
            cwd=self.jobs_root,
            prompt=project.title_plain,
            timeout_s=5,
        )
        now = self.clock.now()
        return LabEvidence(
            id=f"LE-{project.id}",
            project_id=project.id,
            lab_path=str(run.directory),
            role="lab-runner",
            hypothesis="el slug se puede publicar",
            commands=tuple(command),
            result=run.stdout.strip(),
            artifacts=(str(run.directory / "stdout"),),
            verdict="APPROVE",
            evidence_class="running",
            security_check_ref="SC-e2e",
            started_at=now,
            finished_at=now,
            timed_out=run.timed_out,
        )

    def _move(self, project: Project, target: ProjectState) -> Project:
        state = transition(project.state, target)
        return self._remember(replace(project, state=state, updated_at=self.clock.now()))

    def _remember(self, project: Project) -> Project:
        self.ledger.save_project(project)
        self.trace.append(project.state.value)
        return project

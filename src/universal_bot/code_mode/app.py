"""Orquesta el modo código sobre los servicios. Los tests usan FakeDiscord."""

from __future__ import annotations

from universal_bot.code_mode.file_outbox import BridgeDomainError, BridgeTimeout

from dataclasses import replace
import json
from pathlib import Path
import re
import sys

from universal_bot.code_mode.clock import Clock
from universal_bot.code_mode.config import CodeModeConfig, role_allowed
from universal_bot.code_mode.discord_port import DiscordPort
from universal_bot.code_mode.inbox_flow import INSIDE, OUTSIDE, USER_OK, author_roles, confidence_for, should_propose
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
from universal_bot.code_mode.proposer import PROMPT, Proposer
from universal_bot.code_mode.security_gate import SandboxInspection, evaluate
from universal_bot.code_mode.session_manager import SessionManager
from universal_bot.code_mode.stage_router import StageRouter
from universal_bot.code_mode.text_rules import is_manual_trigger, is_trivial_message, strip_activation
from universal_bot.contracts import TriageInput
from universal_bot.triage.classify import classify

FORBIDDEN = "No podés aprobar esto."


class CodeModeApp:
    def __init__(self, db_path, discord: DiscordPort, clock: Clock, config: CodeModeConfig, *, lab_runner=None):
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
        self.lab_runner = lab_runner
        self.ask_bridge = None
        self.stages = StageRouter(discord, db_path=db_path)
        self._op_cursor = 0
        self._requests: dict = {}
        self._actions: dict[str, ProductionAction] = {}

    def handle_job(self, job, job_dir):
        self.begin_ops()
        if job.channel_id not in self.config.allowed_channels:
            self.close_job(job, job_dir, status="skipped", active_step="cerrado", summary="")
            return
        roles = author_roles(job.author.id, self.config)
        if self._session_active(job) or self._activate_manual(job, roles):
            self._route_active(job, job_dir)
            return
        self._route_outside(job, job_dir)

    def resume_proposal(self, job, job_dir, opt: str, user_id: int):
        self.begin_ops()
        roles = author_roles(user_id, self.config)
        if opt == "decline":
            self._say(job, OUTSIDE)
            self.close_job(job, job_dir, status="done", active_step="charla", summary=OUTSIDE)
            return
        if opt.startswith("here_"):
            opened = self.sessions.activate(job.location, user_id, roles, opt[len("here_") :], "proposal_here")
            if not opened.ok:
                return
            self._route_active(job, job_dir)
            return
        if opt == "create_channel":
            self._open_channel(job, job_dir, user_id, roles)
            return
        if opt == "create_thread":
            self._open_project_thread(job, job_dir, user_id, roles)

    def _open_channel(self, job, job_dir, user_id: int, roles: tuple[str, ...]) -> None:
        if not role_allowed(self.config.roles.can_start_project, roles):
            return
        name = f"{self.config.channel_prefix}{_slug(job.prompt)}"
        try:
            channel_id = self.discord.create_channel(
                job.guild_id,
                name,
                category_name=self.config.projects_category,
                parent_id=self.config.admin_category_id,
            )
        except (BridgeTimeout, BridgeDomainError):
            channel_id = None
        if not channel_id:
            self._bridge_failed(job, job_dir, "create_channel")
            return
        opened = self.sessions.activate(
            Location(job.guild_id, channel_id),
            user_id,
            roles,
            "until_exit",
            "project_channel",
            bypass_role_check=True,
        )
        if not opened.ok:
            return
        self._route_active(replace(job, channel_id=channel_id, thread_id=None), job_dir)

    def _open_project_thread(self, job, job_dir, user_id: int, roles: tuple[str, ...]) -> None:
        if not role_allowed(self.config.roles.can_start_thread, roles):
            return
        channel_id = self.config.projects_channel_id or job.channel_id
        name = f"{self.config.channel_prefix}{_slug(job.prompt)}"
        try:
            thread_id = self.discord.create_thread(channel_id, name, wait=True)
        except (BridgeTimeout, BridgeDomainError):
            thread_id = None
        if not thread_id:
            self._bridge_failed(job, job_dir, "create_thread")
            return
        opened = self.sessions.activate(
            Location(job.guild_id, channel_id, thread_id),
            user_id,
            roles,
            "until_exit",
            "project_thread",
            bypass_role_check=True,
        )
        if not opened.ok:
            return
        self._route_active(replace(job, channel_id=channel_id, thread_id=thread_id), job_dir)

    def _bridge_failed(self, job, job_dir, step: str) -> None:
        self.close_job(
            job,
            job_dir,
            status="error",
            active_step=step,
            summary="el puente no confirmó la operación",
            error="bridge_timeout",
        )

    def finish_untested(self, job_dir):
        path = Path(job_dir) / "state.json"
        state = json.loads(path.read_text(encoding="utf-8"))
        if state.get("active_step") != "SANDBOX_CHECK":
            return
        if not self._seguir_accepted(state):
            return
        project = self.ledger.get_project(state["project_id"]) if state.get("project_id") else None
        if project is not None and project.state == ProjectState.WAITING_HUMAN:
            running = self._move(project, ProjectState.RUNNING)
            self._remember(complete_without_production(running, self.clock.now()))
        state["status"] = "done"
        state["active_step"] = "sin-probar"
        state["updated_ts"] = self.clock.now().timestamp()
        state["error"] = None
        path.write_text(json.dumps(state), encoding="utf-8")

    def begin_ops(self):
        ops = getattr(self.discord, "op_ids", None)
        self._op_cursor = 0 if ops is None else len(ops)

    def close_job(self, job, job_dir, *, status, active_step, summary, extra=None, error=None):
        payload = {
            "version": 1,
            "status": status,
            "updated_ts": self.clock.now().timestamp(),
            "summary": summary,
            "active_step": active_step,
            "error": error,
            "op_ids": self._fresh_op_ids(),
            "location_key": job.location_key,
            "session_key": job.session_key,
        }
        if extra:
            payload.update(extra)
        (Path(job_dir) / "state.json").write_text(json.dumps(payload), encoding="utf-8")

    def _session_active(self, job) -> bool:
        session = self.sessions.resolve(job.location)
        return session is not None and session.status == "ACTIVE"

    def _activate_manual(self, job, roles) -> bool:
        if not is_manual_trigger(job.prompt, self.config):
            return False
        opened = self.sessions.handle_text(job.location, job.author.id, roles, job.prompt)
        return opened.ok

    def _route_active(self, job, job_dir):
        if is_trivial_message(job.prompt):
            self._say(job, INSIDE)
            self.close_job(job, job_dir, status="done", active_step="charla", summary=INSIDE)
            return
        orchestrator = getattr(self, "orchestrator", None)
        if orchestrator is not None and self.config.main_enabled:
            orchestrator.start(job, job_dir, strip_activation(job.prompt, self.config))
            return
        self._run_code(job, job_dir)

    def _route_outside(self, job, job_dir):
        decision = classify(TriageInput(text=job.prompt))
        score = confidence_for(decision)
        tier = decision.tier.value
        if should_propose(tier, score, self.config.proposal_threshold, self.config.propose_tiers):
            self.proposer.propose(job.job_id, tier, score, job.location, job.author.id)
            self.close_job(job, job_dir, status="waiting_human", active_step="propose", summary=PROMPT)
            return
        self._say(job, OUTSIDE)
        self.close_job(job, job_dir, status="done", active_step="charla", summary=OUTSIDE)

    def _run_code(self, job, job_dir):
        if self.lab_runner is None:
            self.close_job(job, job_dir, status="error", active_step="lab", summary="sin lab", error="sin lab")
            return
        decision = classify(TriageInput(text=job.prompt))
        project = self._open_project(job, decision)
        hypothesis = strip_activation(job.prompt, self.config)
        outcomes = self.lab_runner.run_hypothesis(
            project_id=project.id,
            slug=project.slug,
            tier=project.tier,
            hypothesis=hypothesis,
        )
        outcome = outcomes[-1]
        if not outcome.launched or outcome.evidence is None:
            self._wait_sandbox(job, job_dir, project, outcome.untested_reason or "sin probar")
            return
        evidence = outcome.evidence
        if evidence.evidence_class != "running" or evidence.verdict != "APPROVE":
            reason = f"sin probar: el lab terminó {evidence.verdict} ({evidence.evidence_class})"
            self._wait_sandbox(job, job_dir, project, reason)
            return
        project = self._move(project, ProjectState.LAB_RUNNING)
        consult = self.lab_runner.consult_maverick(
            project_id=project.id,
            slug=project.slug,
            context=hypothesis,
        )
        project = self._publish(project, outcome.evidence, consult)
        self.stages.post(project, "02-lab", f"Resultado: {outcome.evidence.result}")
        self.stages.post(project, "03-plan", consult)
        self._say(job, USER_OK)
        project = self._move(project, ProjectState.RUNNING)
        self._remember(complete_without_production(project, self.clock.now()))
        self.close_job(
            job,
            job_dir,
            status="done",
            active_step="03-plan",
            summary=USER_OK,
            extra={"project_id": project.id},
        )

    def _open_project(self, job, decision):
        slug = _slug(job.prompt)
        project = self.ledger.create_project(
            guild_id=job.guild_id,
            requester_id=job.author.id,
            origin_message_id=job.message_id,
            slug=slug,
            title_plain=job.prompt[:120],
            tier=decision.tier.value,
            work_type=decision.worktype.value,
            mode=ProjectMode.CHANNEL,
            state=ProjectState.PROVISIONING,
            channel_id=job.channel_id,
            root_thread_id=job.thread_id,
        )
        return self._move(project, ProjectState.SANDBOX_CHECK)

    def publish_worker_result(self, row, result: str) -> str:
        """Resultado del worker del MAIN por el pipeline de etapas: 02-lab con el detalle y 03-plan con la consulta."""
        decision = classify(TriageInput(text=row["prompt"]))
        project = self.ledger.create_project(
            guild_id=row["guild_id"],
            requester_id=row["author_id"],
            origin_message_id=row["origin_message_id"] or row["reply_to"],
            slug=_slug(row["prompt"]),
            title_plain=row["prompt"][:120],
            tier=decision.tier.value,
            work_type=decision.worktype.value,
            mode=ProjectMode.CHANNEL,
            state=ProjectState.PROVISIONING,
            channel_id=row["channel_id"],
            root_thread_id=row["thread_id"],
        )
        project = self._move(self._move(project, ProjectState.SANDBOX_CHECK), ProjectState.LAB_RUNNING)
        self.stages.post(project, "02-lab", f"Resultado del worker:\n{(result or '(sin salida)')[-3000:]}")
        consult_maverick = getattr(self.lab_runner, "consult_maverick", None)
        if consult_maverick is not None:
            consult = consult_maverick(project_id=project.id, slug=project.slug, context=f"{row['prompt']}\n\nResultado:\n{(result or '')[-1500:]}")
            if consult:
                self.stages.post(project, "03-plan", consult)
        return project.id

    def _publish(self, project, evidence, consult):
        plan = Plan(
            project_id=project.id,
            wave="O1",
            steps=(
                PlanStep(
                    id="S1",
                    workstream="lab",
                    summary="probar la hipótesis",
                    paths=(),
                    evidence_refs=(evidence.id,),
                    untested_reason=None,
                ),
            ),
            lab_evidence=(evidence,),
            maverick_consult=consult,
            requires_production=False,
        )
        self.last_plan = plan
        published = publish_plan(
            project,
            plan,
            lab_was_running=True,
            open_questions=(),
            now=self.clock.now(),
        )
        return self._remember(published.project)

    def _wait_sandbox(self, job, job_dir, project, reason: str):
        token = f"resume-{job.job_id}"
        question = self.ask_bridge.ask(
            project_id=project.id,
            stage_key="SANDBOX_CHECK",
            kind="sandbox_check_failed",
            prompt_plain="No pude probarlo en el directorio aparte. ¿Seguimos igual o frenamos?",
            options=("seguir", "frenar"),
            allowed_approvers=(job.author.id,),
            job_id=None,
            resume_token=token,
            channel_id=job.channel_id,
            thread_id=job.thread_id,
        )
        self.close_job(
            job,
            job_dir,
            status="waiting_human",
            active_step="SANDBOX_CHECK",
            summary=reason,
            extra={"resume_token": token, "question_id": question.id, "project_id": project.id},
        )

    def _seguir_accepted(self, state) -> bool:
        if self.ask_bridge is None:
            return False
        question = self.ask_bridge.get(state.get("question_id"))
        return question is not None and question.answer == "seguir"

    def _say(self, job, content: str):
        self.discord.send(
            job.channel_id,
            content,
            thread_id=job.thread_id,
            reply_to=job.reply_to_message_id,
        )

    def _fresh_op_ids(self) -> list[str]:
        ops = getattr(self.discord, "op_ids", None)
        if ops is None:
            return []
        return list(ops[self._op_cursor :])

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


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (cleaned or "lab")[:40]

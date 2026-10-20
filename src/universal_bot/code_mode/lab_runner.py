"""Lab y Maverick contra un CLI inyectable. Los tests no llaman a un modelo real."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
import shutil
from pathlib import Path
import re

import yaml

from universal_bot.code_mode.job_runner import JobRunner
from universal_bot.code_mode.models import LabEvidence
from universal_bot.code_mode.sandbox import bwrap_command, cli_mounts
from universal_bot.code_mode.security_gate import SandboxInspection, evaluate

DEFAULT_ROUTING_POLICY = ""
DEFAULT_LAB_TIMEOUT_S = 900
DEFAULT_MAVERICK_TIMEOUT_S = 300
FALLBACK_ROUTE = ("grok", "grok-4.7", "medium")
_ENV_BASE = ("PATH", "HOME", "LANG", "LC_ALL", "TERM", "TMPDIR")
_SECRET = re.compile(r"TOKEN|KEY|SECRET|PASSWORD|AUTH", re.IGNORECASE)
_SLUG = re.compile(r"[^a-z0-9]+")
_VERDICTS = {"APPROVE", "REVISE", "REJECT", "YIELD", "INCONCLUSIVE"}
_CLASSES = {"running", "paper"}
_LAB_FIELDS = {"hypothesis", "commands", "result", "artifacts", "verdict", "evidence_class"}
_MAV_FIELDS = {"name", "idea", "pros", "cons", "cost", "verdict"}


@dataclass(frozen=True)
class ResolvedRoute:
    cli: str
    model: str
    effort: str


@dataclass(frozen=True)
class LabOutcome:
    evidence: LabEvidence | None
    launched: bool
    untested_reason: str | None


def resolve_route(path, role: str, *, tier: str | None = None) -> ResolvedRoute:
    policy_path = Path(path)
    if not policy_path.is_file():
        return _fallback()
    raw = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
    routes = raw.get("routes") if isinstance(raw, dict) else None
    if not isinstance(routes, list):
        return _fallback()
    for route in routes:
        if not isinstance(route, dict) or route.get("role") != role:
            continue
        tiers = route.get("tier") or []
        if tier is not None and tiers and tier not in tiers:
            continue
        found = _first_usable(route.get("chain") or [])
        if found is not None:
            return found
    return _fallback()


def grok_command(labdir, model: str, effort: str) -> list[str]:
    from universal_bot.code_mode.cli_adapters import grok_argv

    return grok_argv(labdir, model, effort)


def sandbox_env(source, extra=()) -> dict[str, str]:
    allowed = set(_ENV_BASE) | set(extra)
    cleaned: dict[str, str] = {}
    for name in _ENV_BASE + tuple(extra):
        if name not in allowed or name not in source or name in cleaned:
            continue
        if _SECRET.search(name):
            continue
        cleaned[name] = str(source[name])
    return cleaned


def parse_marked_block(stdout: str, marker: str) -> dict | None:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines or not lines[-1].startswith(marker):
        return None
    raw = lines[-1][len(marker) :].strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if marker == "LAB_RESULT:":
        return payload if _valid_lab(payload) else None
    if marker == "MAVERICK_RESULT:":
        return payload if _valid_maverick(payload) else None
    return payload


class LabRunner:
    def __init__(
        self,
        *,
        clock,
        lab_root: Path,
        jobs: JobRunner | None = None,
        routing_policy: Path | str | None = None,
        timeout_s: float = DEFAULT_LAB_TIMEOUT_S,
        maverick_timeout_s: float = DEFAULT_MAVERICK_TIMEOUT_S,
        max_labs_t2: int = 2,
        max_labs_t3: int = 3,
        max_replans: int = 1,
        env_extra: tuple[str, ...] = (),
        environ: dict | None = None,
        command_for=None,
        security_check: str = "on",
        host_role: str = "vps",
        allowlist: tuple[str, ...] = ("pypi.org", "files.pythonhosted.org", "github.com"),
        allow_network: bool = False,
        home: Path | str | None = None,
        which=None,
    ):
        self.clock = clock
        self.lab_root = Path(lab_root)
        self.jobs = jobs if jobs is not None else JobRunner(self.lab_root, clock)
        self.routing_policy = Path(routing_policy) if routing_policy else Path(DEFAULT_ROUTING_POLICY)
        self.timeout_s = timeout_s
        self.maverick_timeout_s = maverick_timeout_s
        self.max_labs_t2 = max_labs_t2
        self.max_labs_t3 = max_labs_t3
        self.max_replans = max_replans
        self.env_extra = tuple(env_extra)
        self.environ = environ
        self.home = Path(home) if home is not None else Path.home()
        self.which = which if which is not None else shutil.which
        self.command_for = command_for
        self.security_check = security_check
        self.host_role = host_role
        self.allowlist = allowlist
        self.allow_network = allow_network
        self.quota = None

    def run_hypothesis(self, *, project_id: str, slug: str, tier: str, hypothesis: str) -> tuple[LabOutcome, ...]:
        limit = self.max_labs_t3 if tier == "T3" else self.max_labs_t2
        outcomes: list[LabOutcome] = []
        replans = 0
        while len(outcomes) < limit:
            outcome = self._one_lab(project_id, slug, tier, hypothesis, len(outcomes) + 1)
            outcomes.append(outcome)
            if not outcome.launched or outcome.evidence is None:
                break
            if outcome.evidence.verdict != "REJECT":
                break
            if replans >= self.max_replans:
                break
            replans += 1
        return tuple(outcomes)

    def consult_maverick(self, *, project_id: str, slug: str, context: str) -> str:
        try:
            outcome = self._spawn(
                project_id=project_id,
                slug=f"mav-{slug}",
                kind="maverick",
                role="maverick",
                tier=None,
                prompt=_maverick_prompt(context),
                timeout_s=self.maverick_timeout_s,
                hypothesis=context,
            )
        except Exception:
            return "sin consulta: error"
        if outcome.untested_reason:
            return f"sin consulta: {outcome.untested_reason}"
        if outcome.evidence is not None and outcome.evidence.timed_out:
            return "sin consulta: timeout"
        parsed = None if outcome.evidence is None else parse_marked_block(outcome.evidence.result, "MAVERICK_RESULT:")
        if parsed is None:
            raw = "" if outcome.evidence is None else outcome.evidence.result
            parsed = parse_marked_block(raw, "MAVERICK_RESULT:")
        if parsed is None:
            return "sin consulta: sin bloque"
        return _render_maverick(parsed)

    def _one_lab(self, project_id: str, slug: str, tier: str, hypothesis: str, number: int) -> LabOutcome:
        return self._spawn(
            project_id=project_id,
            slug=slug,
            kind="lab",
            role="lab",
            tier=tier,
            prompt=_lab_prompt(hypothesis),
            timeout_s=self.timeout_s,
            hypothesis=hypothesis,
            number=number,
        )

    def _spawn(
        self,
        *,
        project_id: str,
        slug: str,
        kind: str,
        role: str,
        tier: str | None,
        prompt: str,
        timeout_s: float,
        hypothesis: str,
        number: int | None = None,
    ) -> LabOutcome:
        folder = self._allocate(slug, number)
        route = resolve_route(self.routing_policy, role, tier=tier)
        if self.quota is not None:
            from universal_bot.code_mode.cli_adapters import choose_cli

            route = choose_cli(self.quota, route)
        command = self._command(route, folder, kind, prompt)
        cleaned = sandbox_env(self._source_env(), self.env_extra)
        decision = evaluate(
            SandboxInspection(
                env=tuple(sorted(cleaned.items())),
                commands=(" ".join(command),),
                write_paths=(str(folder),),
                hosts=(),
                workspace=str(folder),
            ),
            project_id=project_id,
            sandbox_id=folder.name,
            checked_at=self.clock.now(),
            allowlist=self.allowlist,
            security_check=self.security_check,
            host_role=self.host_role,
        )
        if not decision.tests_allowed:
            reason = "sin probar: " + ",".join(decision.result.violations)
            return LabOutcome(None, False, reason)
        run = self.jobs.run(
            slug=folder.name,
            command=command,
            cwd=folder,
            prompt=prompt,
            timeout_s=timeout_s,
            env=cleaned,
            directory=folder,
        )
        return LabOutcome(
            _evidence_from_run(
                project_id=project_id,
                folder=folder,
                command=command,
                hypothesis=hypothesis,
                run=run,
                role_name="maverick" if kind == "maverick" else "lab-runner",
                checked_at=self.clock.now(),
                security_ref=f"SC-{folder.name}",
                number=number or 1,
            ),
            True,
            None,
        )

    def _allocate(self, slug: str, number: int | None) -> Path:
        self.lab_root.mkdir(parents=True, exist_ok=True)
        day = self.clock.now().strftime("%Y-%m-%d")
        safe = _slug(slug)
        if number is not None:
            folder = self.lab_root / f"{day}-{safe}-{number}"
            folder.mkdir(parents=True, exist_ok=True)
            return folder
        index = 1
        while True:
            folder = self.lab_root / f"{day}-{safe}-{index}"
            if not folder.exists():
                folder.mkdir(parents=True)
                return folder
            index += 1

    def _command(self, route: ResolvedRoute, folder: Path, kind: str, prompt: str) -> list[str]:
        from universal_bot.code_mode.cli_adapters import cursor_argv, grok_argv, opencode_argv

        if self.command_for is not None:
            return list(self.command_for(route, folder, kind))
        if route.cli == "cursor-agent":
            inner = cursor_argv(folder, route.model, prompt)
        elif route.cli == "opencode":
            inner = opencode_argv(route.model, prompt)
        elif route.cli == "grok":
            inner = grok_argv(folder, route.model, route.effort)
        else:
            inner = [route.cli, "--model", route.model, "--effort", route.effort, "--cwd", str(folder)]
        network = self.allow_network or route.cli in {"grok", "cursor-agent", "opencode"}
        found = self.which(inner[0]) if inner else None
        binary = Path(os.path.realpath(found)) if found else None
        if binary is not None:
            inner = [str(binary), *inner[1:]]
        binds, layers = cli_mounts(route.cli, self.home, binary)
        return bwrap_command(folder, inner, allow_network=network, ro_binds=binds, home=self.home, overlays=layers)

    def _worker_env(self) -> dict:
        return sandbox_env(self._source_env(), self.env_extra)

    def _source_env(self) -> dict:
        if self.environ is not None:
            return dict(self.environ)
        return dict(os.environ)


def _evidence_from_run(
    *,
    project_id: str,
    folder: Path,
    command: list[str],
    hypothesis: str,
    run,
    role_name: str,
    checked_at: datetime,
    security_ref: str,
    number: int,
) -> LabEvidence:
    parsed = None if run.timed_out else parse_marked_block(run.stdout, "LAB_RESULT:" if role_name == "lab-runner" else "MAVERICK_RESULT:")
    if role_name == "maverick":
        parsed = None
    if run.timed_out or parsed is None:
        body = run.stdout or ""
        return LabEvidence(
            id=f"LE-{project_id}-{number}",
            project_id=project_id,
            lab_path=str(folder),
            role=role_name,
            hypothesis=hypothesis,
            commands=tuple(command),
            result=body.strip(),
            artifacts=(str(folder / "stdout"),),
            verdict="INCONCLUSIVE",
            evidence_class="paper",
            security_check_ref=security_ref,
            started_at=checked_at,
            finished_at=checked_at,
            timed_out=bool(run.timed_out),
        )
    return LabEvidence(
        id=f"LE-{project_id}-{number}",
        project_id=project_id,
        lab_path=str(folder),
        role=role_name,
        hypothesis=str(parsed["hypothesis"]),
        commands=tuple(str(item) for item in parsed["commands"]),
        result=str(parsed["result"]),
        artifacts=tuple(str(item) for item in parsed["artifacts"]),
        verdict=str(parsed["verdict"]),
        evidence_class=str(parsed["evidence_class"]),
        security_check_ref=security_ref,
        started_at=checked_at,
        finished_at=checked_at,
        timed_out=False,
    )


def _lab_prompt(hypothesis: str) -> str:
    return (
        "Probá esta hipótesis en este directorio y en ningún otro.\n"
        f"Hipótesis: {hypothesis}\n"
        "Terminá con una sola línea final, sin texto después:\n"
        "LAB_RESULT: "
        '{"hypothesis":"...","commands":["..."],"result":"...","artifacts":["..."],'
        '"verdict":"APPROVE|REVISE|REJECT|YIELD|INCONCLUSIVE","evidence_class":"running|paper"}\n'
    )


def _maverick_prompt(context: str) -> str:
    return (
        "Proponé alternativas. No decidas el camino.\n"
        f"Contexto: {context}\n"
        "Terminá con una sola línea final:\n"
        "MAVERICK_RESULT: "
        '{"alternatives":[{"name":"...","idea":"...","pros":"...","cons":"...","cost":"...","verdict":"YIELD"}],'
        '"recommendation":"..."}\n'
    )


def _render_maverick(payload: dict) -> str:
    lines = ["CONSULT: propone, no decide."]
    for item in payload["alternatives"]:
        lines.append(
            f"- {item['name']}: {item['idea']} | a favor: {item['pros']} | "
            f"en contra: {item['cons']} | costo: {item['cost']} | {item['verdict']}"
        )
    lines.append(f"Recomendación: {payload['recommendation']}")
    return "\n".join(lines)


def _fallback() -> ResolvedRoute:
    return ResolvedRoute(*FALLBACK_ROUTE)


def _first_usable(chain) -> ResolvedRoute | None:
    if not isinstance(chain, list):
        return None
    for step in chain:
        if not isinstance(step, dict):
            continue
        cli = step.get("cli")
        model = step.get("model")
        effort = step.get("effort")
        if isinstance(cli, str) and cli and isinstance(model, str) and model and isinstance(effort, str) and effort:
            return ResolvedRoute(cli, model, effort)
    return None


def _valid_lab(payload: dict) -> bool:
    if not _LAB_FIELDS <= payload.keys():
        return False
    if payload["verdict"] not in _VERDICTS or payload["evidence_class"] not in _CLASSES:
        return False
    if not isinstance(payload["hypothesis"], str) or not isinstance(payload["result"], str):
        return False
    return _string_list(payload["commands"]) and _string_list(payload["artifacts"])


def _valid_maverick(payload: dict) -> bool:
    alternatives = payload.get("alternatives")
    if not isinstance(payload.get("recommendation"), str) or not isinstance(alternatives, list) or not alternatives:
        return False
    for item in alternatives:
        if not isinstance(item, dict) or not _MAV_FIELDS <= item.keys():
            return False
        if any(not isinstance(item[key], str) for key in _MAV_FIELDS):
            return False
    return True


def _string_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _slug(value: str) -> str:
    cleaned = _SLUG.sub("-", value.strip().lower()).strip("-")
    return cleaned or "lab"

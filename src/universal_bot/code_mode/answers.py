"""Clicks del puente: el primero gana y el stop pausa el job."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from universal_bot.code_mode.config import ApprovalPolicy
from universal_bot.code_mode.models import ProductionAction
from universal_bot.code_mode.prod_gate import approve, reject_production


class AnswerError(ValueError):
    """El click del puente no se puede aplicar."""


@dataclass(frozen=True)
class AppliedClick:
    kind: str
    id: str
    opt: str
    action: ProductionAction | None = None


def consume_answers(
    spool: Path,
    *,
    clock,
    ask_bridge=None,
    projects=None,
    approvals=None,
    role_lookup=None,
) -> tuple[AppliedClick, ...]:
    root = Path(spool)
    applied = _load_applied(root)
    events: list[AppliedClick] = []
    folder = root / "answers"
    if not folder.is_dir():
        return ()
    for path in sorted(folder.glob("*.json")):
        if path.name in applied:
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("version") != 1:
            raise AnswerError("version distinta de 1")
        kind = str(raw["kind"])
        item_id = str(raw["id"])
        expected = f"{kind}__{item_id}.json"
        if path.name != expected:
            raise AnswerError(f"nombre distinto del click: {path.name}")
        event = _apply(root, raw, clock, ask_bridge, projects, approvals, role_lookup)
        applied.add(path.name)
        _save_applied(root, applied)
        events.append(event)
    return tuple(events)


def _apply(spool, raw, clock, ask_bridge, projects, approvals, role_lookup) -> AppliedClick:
    kind = str(raw["kind"])
    item_id = str(raw["id"])
    opt = str(raw["opt"])
    if kind == "pq":
        if ask_bridge is None:
            raise AnswerError("falta ask_bridge")
        ask_bridge.answer(item_id, opt, _num(raw["user_id"]))
        return AppliedClick(kind, item_id, opt)
    if kind == "prod":
        return _apply_prod(raw, projects, approvals, role_lookup, clock)
    if kind == "stop":
        _apply_stop(spool, item_id, projects, clock)
        return AppliedClick(kind, item_id, opt)
    if kind == "propose":
        raise NotImplementedError
    raise AnswerError(f"kind desconocido: {kind}")


def _apply_prod(raw, projects, approvals, role_lookup, clock) -> AppliedClick:
    if projects is None:
        raise AnswerError("falta el libro de proyectos")
    item_id = str(raw["id"])
    opt = str(raw["opt"])
    project = projects.get_project(item_id)
    if project is None:
        raise AnswerError(f"no está el proyecto {item_id}")
    policy = approvals or ApprovalPolicy()
    if opt == "reject":
        projects.save_project(reject_production(project, clock.now()))
        return AppliedClick("prod", item_id, opt)
    if opt != "approve":
        raise AnswerError(f"opt de producción desconocida: {opt}")
    user_id = _num(raw["user_id"])
    roles = tuple(role_lookup(user_id)) if role_lookup else ()
    action = ProductionAction(project.id, "deploy", "prod", "pase a producción")
    decision = approve(project, action, user_id, roles, policy, clock.now())
    if decision.accepted:
        projects.save_project(decision.project)
        return AppliedClick("prod", item_id, opt, decision.action)
    return AppliedClick("prod", item_id, opt, None)


def _apply_stop(spool: Path, job_id: str, projects, clock) -> None:
    job_dir = _find_job(spool, job_id)
    if job_dir is None:
        raise AnswerError(f"no está el job {job_id}")
    path = job_dir / "state.json"
    raw = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"version": 1}
    project_id = raw.get("project_id")
    raw["version"] = 1
    raw["status"] = "paused"
    raw["updated_ts"] = clock.now().timestamp()
    raw["summary"] = "stop"
    raw["error"] = None
    path.write_text(json.dumps(raw), encoding="utf-8")
    if project_id and projects is not None:
        projects.request_checkpoint(str(project_id))


def _find_job(spool: Path, job_id: str) -> Path | None:
    inbox = spool / "inbox"
    if not inbox.is_dir():
        return None
    for job_json in inbox.glob("*/job.json"):
        raw = json.loads(job_json.read_text(encoding="utf-8"))
        if str(raw.get("job_id")) == job_id:
            return job_json.parent
    return None


def _load_applied(spool: Path) -> set[str]:
    path = spool / "runtime" / "answers_applied.json"
    if not path.is_file():
        return set()
    return set(json.loads(path.read_text(encoding="utf-8")))


def _save_applied(spool: Path, names: set[str]) -> None:
    path = spool / "runtime" / "answers_applied.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(names)), encoding="utf-8")


def _num(value: object) -> int:
    text = str(value)
    if not text.isdigit():
        raise AnswerError("user_id no es numérico")
    return int(text)

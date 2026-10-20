"""Cada job del inbox entra por acá. El reloj y el lab se inyectan."""

from __future__ import annotations

import json
from pathlib import Path

from universal_bot.code_mode.inbox_job import load_inbox_job

OUTSIDE = "esto lo atiende el bot normal: usá el prefijo de siempre"
INSIDE = "esto lo atiende el bot normal, usá el prefijo"
USER_OK = (
    "Se puede hacer. Lo probé en un directorio aparte y anduvo. "
    "El detalle está en los hilos de cada etapa. "
    "No hace falta una aprobación para seguir con la prueba."
)

_DEFAULT_ROLES = (
    ("910004", ("@dev", "@admin")),
    ("910006", ("@dev", "@admin")),
)

_CONFIDENCE = {
    ("refactor",): 0.91,
    ("multi-workstream",): 0.90,
    ("feature",): 0.92,
    ("automation", "vague"): 0.85,
    ("irreversible", "prod-risk"): 0.95,
    ("env-anomaly",): 0.55,
    ("bug", "single-file"): 0.50,
    ("bug", "two-files"): 0.50,
    ("typo",): 0.20,
    ("non-code",): 0.10,
    ("read-only",): 0.10,
    ("empty",): 0.0,
    ("default-cheapest",): 0.40,
    ("desconocido",): 0.0,
}


def confidence_for(decision) -> float:
    return _CONFIDENCE.get(tuple(decision.signals), 0.0)


def should_propose(tier, confidence, threshold, tiers) -> bool:
    return tier in tuple(tiers) and confidence >= threshold


def author_roles(author_id, config) -> tuple[str, ...]:
    table = _DEFAULT_ROLES if config.role_map is None else config.role_map
    key = str(author_id)
    for snowflake, roles in table:
        if snowflake == key:
            return tuple(roles)
    return ()


def apply_clicks(app, spool, clicks) -> None:
    root = Path(spool)
    for click in clicks:
        if click.kind == "propose":
            _propose_click(app, root, click)
        elif click.kind == "pq" and click.opt == "seguir":
            job_dir = _job_with_question(root, click.id)
            if job_dir is not None:
                app.finish_untested(job_dir)


def _propose_click(app, spool: Path, click) -> None:
    job_dir = _job_dir(spool, click.id)
    if job_dir is None:
        return
    raw = json.loads((spool / "answers" / f"propose__{click.id}.json").read_text(encoding="utf-8"))
    app.resume_proposal(load_inbox_job(job_dir), job_dir, click.opt, int(str(raw["user_id"])))


def _job_dir(spool: Path, job_id: str) -> Path | None:
    inbox = spool / "inbox"
    if not inbox.is_dir():
        return None
    for path in inbox.glob("*/job.json"):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if str(raw.get("job_id")) == job_id:
            return path.parent
    return None


def _job_with_question(spool: Path, question_id: str) -> Path | None:
    inbox = spool / "inbox"
    if not inbox.is_dir():
        return None
    for path in inbox.glob("*/state.json"):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if str(raw.get("question_id")) == question_id:
            return path.parent
    return None

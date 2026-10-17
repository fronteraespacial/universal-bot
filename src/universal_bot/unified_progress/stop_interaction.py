"""Parse Discord ``INTERACTION_CREATE`` for the unified progress stop button.

The host gateway receives component clicks, calls
:func:`handle_stop_interaction`, then posts the returned body to Discord's
interaction callback URL. Job kill and :meth:`LiveTrail.finish` stay in the host.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from universal_bot.unified_progress.stop_control import parse_stop_button_custom_id
from universal_bot.unified_progress.trail import read_marker

# Discord interaction / response types (subset we need).
INTERACTION_MESSAGE_COMPONENT = 3
RESPONSE_CHANNEL_MESSAGE = 4
RESPONSE_DEFERRED_UPDATE = 6

FLAG_EPHEMERAL = 1 << 6


class StopOutcome(str, Enum):
    NOT_STOP_BUTTON = "not_stop_button"
    DENIED = "denied"
    NO_MARKER = "no_marker"
    NO_JOB = "no_job"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class StopButtonClick:
    channel_id: str
    job_id: str
    user_id: str
    interaction_id: str
    interaction_token: str


def _interaction_user_id(payload: dict[str, Any]) -> str:
    member = payload.get("member")
    if isinstance(member, dict):
        user = member.get("user")
        if isinstance(user, dict) and user.get("id"):
            return str(user["id"])
    user = payload.get("user")
    if isinstance(user, dict) and user.get("id"):
        return str(user["id"])
    return ""


def parse_stop_button_interaction(payload: dict[str, Any]) -> StopButtonClick | None:
    """Return click details when ``payload`` is a stop-button component interaction."""
    if int(payload.get("type") or 0) != INTERACTION_MESSAGE_COMPONENT:
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    parsed = parse_stop_button_custom_id(str(data.get("custom_id") or ""))
    if not parsed:
        return None
    channel_id, job_id = parsed
    user_id = _interaction_user_id(payload)
    iid = str(payload.get("id") or "").strip()
    token = str(payload.get("token") or "").strip()
    if not user_id or not iid or not token:
        return None
    return StopButtonClick(
        channel_id=channel_id,
        job_id=job_id,
        user_id=user_id,
        interaction_id=iid,
        interaction_token=token,
    )


def stop_acl_allowed(
    *,
    clicker_id: str,
    marker_author_id: str | None,
    admin_ids: set[str] | frozenset[str],
) -> bool:
    """True when the clicker is the job author or a configured Discord admin."""
    uid = str(clicker_id or "").strip()
    if not uid:
        return False
    if uid in set(admin_ids):
        return True
    author = str(marker_author_id or "").strip()
    return bool(author) and uid == author


def interaction_response(
    content: str,
    *,
    ephemeral: bool = True,
    response_type: int = RESPONSE_CHANNEL_MESSAGE,
) -> dict[str, Any]:
    """JSON body for ``POST …/interactions/{id}/{token}/callback``."""
    data: dict[str, Any] = {"content": (content or "")[:2000]}
    if ephemeral:
        data["flags"] = FLAG_EPHEMERAL
    return {"type": response_type, "data": data}


def interaction_deferred_update() -> dict[str, Any]:
    """Ack a component click without a visible message (rare for stop; prefer ephemeral)."""
    return {"type": RESPONSE_DEFERRED_UPDATE}


@dataclass(frozen=True)
class StopHandleResult:
    outcome: StopOutcome
    response: dict[str, Any] | None = None
    click: StopButtonClick | None = None


def handle_stop_interaction(
    payload: dict[str, Any],
    *,
    state_dir: Path | str,
    admin_ids: set[str] | frozenset[str],
    cancel_job: Callable[[str, str], bool],
    cancel_note: Callable[[StopButtonClick], str] | None = None,
) -> StopHandleResult:
    """Evaluate ACL, cancel one job, return the interaction callback payload.

    ``cancel_job(channel_id, job_id)`` must kill the host subprocess and release
    inflight; return True when a job was stopped. The host should call
    ``LiveTrail.finish(ok=False, note=…)`` from the same cancel path (or inside
    ``cancel_job``) so the card drops the button.
    """
    click = parse_stop_button_interaction(payload)
    if click is None:
        return StopHandleResult(outcome=StopOutcome.NOT_STOP_BUTTON)

    marker = read_marker(state_dir, click.channel_id, click.job_id, require_alive=False)
    if not marker and str(click.user_id) not in set(admin_ids):
        return StopHandleResult(
            outcome=StopOutcome.NO_MARKER,
            click=click,
            response=interaction_response("Ese pedido ya no está activo."),
        )

    author_id = str((marker or {}).get("author_id") or "") or None
    if not stop_acl_allowed(
        clicker_id=click.user_id,
        marker_author_id=author_id,
        admin_ids=admin_ids,
    ):
        return StopHandleResult(
            outcome=StopOutcome.DENIED,
            click=click,
            response=interaction_response("No tenés permiso para detener este pedido."),
        )

    stopped = cancel_job(click.channel_id, click.job_id)
    if not stopped:
        return StopHandleResult(
            outcome=StopOutcome.NO_JOB,
            click=click,
            response=interaction_response("No encontré un job activo para ese botón."),
        )

    if cancel_note:
        note = cancel_note(click)
    else:
        note = "Cancelado desde la tarjeta de progreso."
    return StopHandleResult(
        outcome=StopOutcome.CANCELLED,
        click=click,
        response=interaction_response(note),
    )

"""Progress-contract v1 consumer for Universal Bot.

UB does not post Discord digests itself yet. This scheduler is the single
publisher decision point so a future poster cannot invent a second dialect.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

try:
    from progress_contract import (
        PROGRESS_FRESH_S,
        PROGRESS_INTERVAL_S,
        ProgressEvent,
        ProgressPublisher,
        event_from_mapping,
        format_event,
    )
except ImportError:  # pragma: no cover
    PROGRESS_FRESH_S = 180
    PROGRESS_INTERVAL_S = 120
    ProgressEvent = None  # type: ignore[assignment]
    ProgressPublisher = None  # type: ignore[assignment]
    event_from_mapping = None  # type: ignore[assignment]
    format_event = None  # type: ignore[assignment]


@dataclass
class ScheduledDigest:
    publish: bool
    reason: str
    text: str
    updates_real_activity: bool
    event: dict[str, Any]


class ProgressScheduler:
    """One publisher per job. Same cadence / formatter as the pack."""

    def __init__(
        self,
        *,
        interval_s: float = PROGRESS_INTERVAL_S,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if ProgressPublisher is None:
            raise RuntimeError("progress_contract is not installed")
        self.interval_s = float(interval_s)
        self._pub = ProgressPublisher(interval_s=self.interval_s, clock=clock)

    def observe(self, payload: dict[str, Any], *, now: float | None = None) -> ScheduledDigest:
        if event_from_mapping is None:
            raise RuntimeError("progress_contract is not installed")
        ev = event_from_mapping(payload)
        decision = self._pub.decide(ev, now=now)
        text = decision.text or ""
        if decision.publish and not text and format_event is not None:
            text = format_event(ev, now=now)
        if decision.publish:
            self._pub.mark_sent(ev.job_id, sent_at=now)
        return ScheduledDigest(
            publish=decision.publish,
            reason=decision.reason,
            text=text,
            updates_real_activity=decision.updates_real_activity,
            event=ev.to_dict(),
        )


def freshness_window_s(progress_freshness_s: float | None = None) -> float:
    return float(progress_freshness_s if progress_freshness_s is not None else PROGRESS_FRESH_S)

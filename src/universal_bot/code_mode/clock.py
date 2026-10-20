"""Reloj inyectable. Los tests usan FakeClock."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FakeClock:
    def __init__(self, now: datetime):
        if now.tzinfo is None:
            raise ValueError("FakeClock exige datetime con zona horaria")
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, *, seconds: int = 0, minutes: int = 0, hours: int = 0) -> datetime:
        self._now = self._now + timedelta(seconds=seconds, minutes=minutes, hours=hours)
        return self._now

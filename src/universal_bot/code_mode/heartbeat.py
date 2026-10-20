"""Heartbeat del runtime. Si pasa de 60 s, FE-BOT dice que no está."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

_NAME = "runtime.heartbeat"
_FRESH_S = 20
_STALE_S = 60


def touch_heartbeat(spool: Path, clock) -> None:
    (Path(spool) / _NAME).write_text(clock.now().isoformat(), encoding="utf-8")


def heartbeat_fresh(spool: Path, clock) -> bool:
    age = _age(spool, clock)
    return age is not None and age <= _FRESH_S


def heartbeat_status(spool: Path, clock) -> str:
    age = _age(spool, clock)
    if age is None or age > _STALE_S:
        return "no disponible"
    return "ok"


def _age(spool: Path, clock) -> float | None:
    path = Path(spool) / _NAME
    if not path.is_file():
        return None
    stamped = datetime.fromisoformat(path.read_text(encoding="utf-8").strip())
    return (clock.now() - stamped).total_seconds()


class HeartbeatThread:
    def __init__(self, *args, **kwargs):
        raise NotImplementedError

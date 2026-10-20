"""Heartbeat del runtime. Si pasa de 60 s, FE-BOT dice que no está."""

from __future__ import annotations

from pathlib import Path


def touch_heartbeat(spool: Path, clock) -> None:
    raise NotImplementedError("touch_heartbeat")


def heartbeat_fresh(spool: Path, clock) -> bool:
    raise NotImplementedError("heartbeat_fresh")


def heartbeat_status(spool: Path, clock) -> str:
    raise NotImplementedError("heartbeat_status")

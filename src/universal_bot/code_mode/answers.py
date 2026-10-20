"""Clicks del puente: el primero gana y el stop pausa el job."""

from __future__ import annotations

from pathlib import Path


def consume_answers(spool: Path, *, clock, ask_bridge=None, projects=None, approvals=None, role_lookup=None) -> tuple:
    raise NotImplementedError("consume_answers")

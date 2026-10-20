"""Lab y Maverick contra un CLI inyectable. Los tests no llaman a un modelo real."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


DEFAULT_ROUTING_POLICY = "/workspace/codemode-base/catalog/routing-policy.yaml"
DEFAULT_LAB_TIMEOUT_S = 900
DEFAULT_MAVERICK_TIMEOUT_S = 300


@dataclass(frozen=True)
class ResolvedRoute:
    cli: str
    model: str
    effort: str


@dataclass(frozen=True)
class LabOutcome:
    evidence: object
    launched: bool
    untested_reason: str | None


def resolve_route(path, role, *, tier=None):
    raise NotImplementedError


def grok_command(labdir, model, effort):
    raise NotImplementedError


def sandbox_env(source, extra=()):
    raise NotImplementedError


def parse_marked_block(stdout, marker):
    raise NotImplementedError


class LabRunner:
    def __init__(self, **kwargs):
        raise NotImplementedError

    def run_hypothesis(self, **kwargs):
        raise NotImplementedError

    def consult_maverick(self, **kwargs):
        raise NotImplementedError

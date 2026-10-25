"""Alarmas de Augmented Coding para el verifier.

Loops, scope creep y fake tests son FAIL. Si la señal no alcanza para
descartarlas (historia, aceptación, fuera de alcance, slice con tests),
no hay PASS: falla cerrado.
"""

from __future__ import annotations

from dataclasses import dataclass

LOOPS = "loops"
SCOPE_CREEP = "scope_creep"
FAKE_TESTS = "fake_tests"


@dataclass(frozen=True)
class ProgressSignal:
    """Lo que se vio del worker en un paso. Lo que no está, no se da por bueno."""

    story: str = ""
    acceptance: tuple[str, ...] = ()
    out_of_scope: tuple[str, ...] = ()
    approach: str = ""
    prior_approaches: tuple[str, ...] = ()
    changed_paths: tuple[str, ...] = ()
    allowed_paths: tuple[str, ...] = ()
    tests_changed: tuple[str, ...] = ()
    production_changed: tuple[str, ...] = ()
    tests_proven_wrong: bool = False
    evidence: str = ""
    new_info: bool = False


@dataclass(frozen=True)
class AlarmVerdict:
    ok: bool
    alarms: tuple[str, ...]
    reasons: tuple[str, ...]


def classify(signal: ProgressSignal) -> AlarmVerdict:
    """Clasifica la señal. Sin alarma nombrada igual puede fallar cerrado."""
    alarms: list[str] = []
    reasons: list[str] = []

    if signal.approach and signal.approach in signal.prior_approaches and not signal.new_info:
        alarms.append(LOOPS)
        reasons.append("repeated_approach")

    touched = _touched(signal)
    outside = _outside(signal, touched)
    if outside:
        alarms.append(SCOPE_CREEP)
        reasons.extend(f"outside:{path}" for path in outside)
    if touched and not signal.allowed_paths:
        reasons.append("missing_allowlist")

    if signal.tests_changed and not signal.production_changed and not signal.tests_proven_wrong:
        alarms.append(FAKE_TESTS)
        reasons.append("tests_edited_to_pass")

    if not signal.story.strip():
        reasons.append("missing_story")
    if not signal.acceptance:
        reasons.append("missing_acceptance")
    if not signal.out_of_scope:
        reasons.append("missing_out_of_scope")
    if not signal.approach.strip():
        reasons.append("missing_approach")
    if not touched:
        reasons.append("missing_changes")
    if signal.evidence != "tests":
        reasons.append("missing_test_evidence")

    blocked = any(item.startswith("missing_") for item in reasons)
    return AlarmVerdict(not alarms and not blocked, tuple(alarms), tuple(reasons))


def _touched(signal: ProgressSignal) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for path in (*signal.changed_paths, *signal.tests_changed, *signal.production_changed):
        if path:
            seen.setdefault(path, None)
    return tuple(seen)


def _outside(signal: ProgressSignal, touched: tuple[str, ...]) -> tuple[str, ...]:
    parked = set(signal.out_of_scope)
    found: dict[str, None] = {}
    for path in touched:
        if path in parked or (signal.allowed_paths and not _covered(path, signal.allowed_paths)):
            found.setdefault(path, None)
    return tuple(found)


def _covered(path: str, allowed: tuple[str, ...]) -> bool:
    for raw in allowed:
        root = raw.rstrip("/")
        if root and (path == root or path.startswith(root + "/")):
            return True
    return False

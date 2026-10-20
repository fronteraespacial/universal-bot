"""Table-driven tests for deterministic triage classify()."""

from __future__ import annotations

import pytest

from universal_bot.contracts import Tier, TriageInput, WorkType
from universal_bot.triage.classify import classify


def _decide(
    text: str,
    paths: tuple[str, ...] = (),
) -> tuple[Tier, bool, WorkType | None, frozenset[str]]:
    d = classify(TriageInput(text=text, mentioned_paths=paths))
    return d.tier, d.is_code, d.worktype, frozenset(d.signals)


@pytest.mark.parametrize(
    "text,paths,exp_tier,exp_is_code,exp_worktype,required_signals",
    [
        (
            "arreglá el typo 'recieve' en README",
            ("README.md",),
            Tier.T0,
            True,
            None,
            frozenset({"typo"}),
        ),
        (
            "¿dónde está el dispatcher?",
            (),
            Tier.T0,
            False,
            None,
            frozenset({"read-only"}),
        ),
        (
            "el lock no se libera al cancelar, en locks.py",
            ("locks.py",),
            Tier.T1,
            True,
            None,
            frozenset({"bug", "single-file"}),
        ),
        (
            "bug en store.py y dispatcher.py con el lease",
            ("store.py", "dispatcher.py"),
            Tier.T1,
            True,
            None,
            frozenset({"bug", "two-files"}),
        ),
        (
            "refactor del progress en módulos separados",
            (),
            Tier.T2,
            True,
            None,
            frozenset({"refactor"}),
        ),
        (
            "agregá contrato + adaptador para codex",
            ("a.py", "b.py", "c.py"),
            Tier.T2,
            True,
            None,
            frozenset({"multi-workstream"}),
        ),
        (
            "que el bot programe solo y abra PRs",
            (),
            Tier.T3,
            True,
            None,
            frozenset({"automation", "vague"}),
        ),
        (
            "feature nueva: puente de preguntas a Discord",
            (),
            Tier.T3,
            True,
            None,
            frozenset({"feature"}),
        ),
        (
            "migrá la base de prod y borrá la tabla vieja",
            (),
            Tier.T3,
            True,
            None,
            frozenset({"irreversible"}),
        ),
        (
            "",
            (),
            Tier.T0,
            False,
            None,
            frozenset({"empty"}),
        ),
        (
            "hola, ¿cómo andás?",
            (),
            Tier.T0,
            False,
            None,
            frozenset({"non-code"}),
        ),
        (
            "falla solo en WSL detrás del proxy",
            (),
            None,
            True,
            WorkType.OPS_DIAGNOSTIC,
            frozenset({"env-anomaly"}),
        ),
    ],
    ids=[
        "typo-readme",
        "where-dispatcher",
        "lock-bug-one-file",
        "lease-bug-two-files",
        "refactor-progress",
        "contrato-adaptador",
        "automation-prs",
        "feature-discord",
        "prod-migrate-irreversible",
        "empty-input",
        "social-greeting",
        "wsl-proxy-env",
    ],
)
def test_classify_table(
    text: str,
    paths: tuple[str, ...],
    exp_tier: Tier | None,
    exp_is_code: bool,
    exp_worktype: WorkType | None,
    required_signals: frozenset[str],
) -> None:
    tier, is_code, worktype, signals = _decide(text, paths)
    if exp_tier is not None:
        assert tier == exp_tier
    if exp_worktype is not None:
        assert worktype == exp_worktype
    assert is_code == exp_is_code
    assert required_signals <= signals

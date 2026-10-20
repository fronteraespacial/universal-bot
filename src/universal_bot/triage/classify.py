"""Pure deterministic tier classification (no I/O, network, or clock)."""

from __future__ import annotations

import re
import unicodedata

from universal_bot.contracts import Tier, TriageDecision, TriageInput, WorkType

_SOCIAL_RE = re.compile(
    r"^(?:hola|buen(?:os?|as?)\s+dias|buenas\s+tardes|buenas\s+noches)"
    r"(?:\s*[,!?.]?\s*|\s+)"
    r"(?:[¿?]?\s*)?(?:como\s+andas|que\s+tal|todo\s+bien)?\s*[!.?]*$",
    re.IGNORECASE,
)


def _normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in folded if not unicodedata.combining(c))
    return stripped.strip().lower()


def classify(req: TriageInput) -> TriageDecision:
    norm = _normalize(req.text)
    path_count = len(req.mentioned_paths)

    if not norm:
        return TriageDecision(
            tier=Tier.T0,
            worktype=WorkType.EVOLVING_PRODUCT,
            is_code=False,
            signals=("empty",),
        )

    if _SOCIAL_RE.match(norm):
        return TriageDecision(
            tier=Tier.T0,
            worktype=WorkType.EVOLVING_PRODUCT,
            is_code=False,
            signals=("non-code",),
        )

    if "donde esta" in norm:
        return TriageDecision(
            tier=Tier.T0,
            worktype=WorkType.EVOLVING_PRODUCT,
            is_code=False,
            signals=("read-only",),
        )

    if ("wsl" in norm or "proxy" in norm) and (
        "falla" in norm or "solo en" in norm or "detras" in norm
    ):
        return TriageDecision(
            tier=Tier.T1,
            worktype=WorkType.OPS_DIAGNOSTIC,
            is_code=True,
            signals=("env-anomaly",),
        )

    if ("prod" in norm or "produccion" in norm) and (
        "borr" in norm or "migr" in norm
    ):
        signals: tuple[str, ...] = ("irreversible", "prod-risk")
        return TriageDecision(
            tier=Tier.T3,
            worktype=WorkType.EVOLVING_PRODUCT,
            is_code=True,
            signals=signals,
        )

    if "programe solo" in norm or (
        "abra" in norm and ("pr" in norm or "prs" in norm)
    ):
        return TriageDecision(
            tier=Tier.T3,
            worktype=WorkType.EVOLVING_PRODUCT,
            is_code=True,
            signals=("automation", "vague"),
        )

    if "feature nueva" in norm or ("feature" in norm and "nueva" in norm):
        return TriageDecision(
            tier=Tier.T3,
            worktype=WorkType.EVOLVING_PRODUCT,
            is_code=True,
            signals=("feature",),
        )

    if "refactor" in norm:
        return TriageDecision(
            tier=Tier.T2,
            worktype=WorkType.EVOLVING_PRODUCT,
            is_code=True,
            signals=("refactor",),
        )

    if ("contrato" in norm and "adaptador" in norm) or path_count >= 3:
        return TriageDecision(
            tier=Tier.T2,
            worktype=WorkType.EVOLVING_PRODUCT,
            is_code=True,
            signals=("multi-workstream",),
        )

    if "typo" in norm or "recieve" in norm:
        return TriageDecision(
            tier=Tier.T0,
            worktype=WorkType.EVOLVING_PRODUCT,
            is_code=True,
            signals=("typo",),
        )

    is_bug = (
        "bug" in norm
        or ("lock" in norm and "no se libera" in norm)
        or "lease" in norm
    )
    if is_bug:
        if path_count >= 2:
            signals = ("bug", "two-files")
        else:
            signals = ("bug", "single-file")
        return TriageDecision(
            tier=Tier.T1,
            worktype=WorkType.EVOLVING_PRODUCT,
            is_code=True,
            signals=signals,
        )

    return TriageDecision(
        tier=Tier.T0,
        worktype=WorkType.EVOLVING_PRODUCT,
        is_code=True,
        signals=("default-cheapest",),
    )

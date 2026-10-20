"""Pure deterministic tier classification (no I/O, network, or clock)."""

from universal_bot.contracts import TriageDecision, TriageInput


def classify(req: TriageInput) -> TriageDecision:
    raise NotImplementedError("classify is not implemented yet")

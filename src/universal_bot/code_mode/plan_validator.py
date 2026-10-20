"""El plan se publica solo si cada paso tiene evidencia real o un «sin probar» consultado."""

from __future__ import annotations


class PlanRejection(Exception):
    def __init__(self, reasons: tuple[str, ...]):
        super().__init__(", ".join(reasons))
        self.reasons = reasons


def validate_plan(*args, **kwargs):
    raise NotImplementedError("validate_plan")


def publish_plan(*args, **kwargs):
    raise NotImplementedError("publish_plan")

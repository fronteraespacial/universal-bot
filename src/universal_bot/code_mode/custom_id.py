"""custom_id del puente: ublab:<kind>:<id>:<opt>."""

from __future__ import annotations

from dataclasses import dataclass


class CustomIdError(ValueError):
    """El custom_id no cumple el contrato del puente."""


@dataclass(frozen=True)
class CustomId:
    kind: str
    id: str
    opt: str

    @property
    def is_stop(self) -> bool:
        return self.kind == "stop"


def build_custom_id(kind: str, item_id: str, opt: str) -> str:
    raise NotImplementedError("build_custom_id")


def parse_custom_id(value: str) -> CustomId:
    raise NotImplementedError("parse_custom_id")

"""custom_id del puente: ublab:<kind>:<id>:<opt>."""

from __future__ import annotations

from dataclasses import dataclass
import re

_PART = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_PREFIX = "ublab:"
_MAX = 100


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
    raw = f"{_PREFIX}{kind}:{item_id}:{opt}"
    parse_custom_id(raw)
    return raw


def parse_custom_id(value: str) -> CustomId:
    if not isinstance(value, str) or not value.startswith(_PREFIX):
        raise CustomIdError(f"custom_id ajeno: {value!r}")
    if len(value) > _MAX:
        raise CustomIdError("custom_id inválido: supera 100 caracteres")
    parts = value[len(_PREFIX):].split(":")
    if len(parts) != 3:
        raise CustomIdError("custom_id inválido: se esperan exactamente tres partes")
    kind, item_id, opt = parts
    if not (_PART.fullmatch(kind) and _PART.fullmatch(item_id) and _PART.fullmatch(opt)):
        raise CustomIdError("custom_id inválido: parte vacía o con caracteres no permitidos")
    return CustomId(kind, item_id, opt)

"""Chequeo automático del sandbox antes de correr pruebas."""

from __future__ import annotations

from datetime import datetime


class SandboxInspection:
    def __init__(self, *args, **kwargs):
        raise NotImplementedError("SandboxInspection")


def evaluate(*args, **kwargs):
    raise NotImplementedError("evaluate")


def validate_security_config(security_check: str, host_role: str) -> None:
    raise NotImplementedError("validate_security_config")

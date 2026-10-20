"""Procesos fijos (warm) de los CLIs. Pendiente de implementar."""

CAPABILITIES = {}


class WarmError(Exception):
    pass


class TurnResult:
    pass


class WarmPool:
    def __init__(self, *args, **kwargs):
        raise NotImplementedError


def make_session(*args, **kwargs):
    raise NotImplementedError


def warm_argv(*args, **kwargs):
    raise NotImplementedError

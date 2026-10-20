"""Cerebros del MAIN: cursor-sdk (sidecar, steer por archivo), cursor-agent (matar y relanzar) y fallback."""


class SidecarSession:
    def __init__(self, *a, **k):
        raise NotImplementedError


class RelaunchSession:
    def __init__(self, *a, **k):
        raise NotImplementedError


class FallbackSession:
    def __init__(self, *a, **k):
        raise NotImplementedError


def select_main_session(*a, **k):
    raise NotImplementedError

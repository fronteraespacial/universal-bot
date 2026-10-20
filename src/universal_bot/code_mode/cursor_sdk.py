"""Adaptador Python del sidecar cursor-sdk."""


def sdk_request(*args, **kwargs):
    raise NotImplementedError


def sidecar_argv(*args, **kwargs):
    raise NotImplementedError


def sidecar_env(*args, **kwargs):
    raise NotImplementedError


class CursorSdkAdapter:
    def __init__(self, *args, **kwargs):
        raise NotImplementedError


def run_with_fallback(*args, **kwargs):
    raise NotImplementedError


class SdkOutcome:
    def __init__(self, *args, **kwargs):
        raise NotImplementedError

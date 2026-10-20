"""Adaptadores de CLI y elección por cuota. El feat completa los comandos."""


def grok_argv(labdir, model: str, effort: str) -> list[str]:
    del labdir, model, effort
    raise NotImplementedError


def cursor_argv(labdir, model: str, prompt: str) -> list[str]:
    del labdir, model, prompt
    raise NotImplementedError


def opencode_argv(model: str, prompt: str) -> list[str]:
    del model, prompt
    raise NotImplementedError


def choose_cli(reader, policy_route):
    del reader, policy_route
    raise NotImplementedError


class FileQuotaReader:
    def __init__(self, path):
        self.path = path

    def grok_remaining(self) -> float:
        raise NotImplementedError

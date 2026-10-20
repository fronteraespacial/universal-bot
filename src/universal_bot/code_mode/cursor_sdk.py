"""Adaptador Python del sidecar cursor-sdk (adapters/cursor_sdk, contrato en docs/cursor-sdk-sidecar.md)."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

DEFAULT_MODEL = "composer-2.5"
DEFAULT_TIMEOUT_S = 120
DEFAULT_GRACE_S = 15.0
ENV_WHITELIST = ("PATH", "HOME", "LANG", "LC_ALL", "TERM", "TMPDIR")


@dataclass(frozen=True)
class SdkOutcome:
    ok: bool
    text: str
    code: str | None
    fallback: bool
    usage: dict | None
    run_id: str | None
    duration_ms: int | None
    events: tuple
    message: str = ""


@dataclass(frozen=True)
class ChatResult:
    cli: str
    text: str
    sdk: SdkOutcome | None


def sdk_request(
    prompt: str,
    *,
    cwd: str,
    model: str = DEFAULT_MODEL,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    stream: bool = False,
    system: str | None = None,
    steer_file: str | None = None,
) -> dict:
    request = {"prompt": prompt, "model": model, "cwd": cwd, "timeout_s": timeout_s, "stream": stream}
    if system:
        request["system"] = system
    if steer_file:
        request["steer_file"] = steer_file
    return request


def sidecar_argv(launcher, key_file) -> list[str]:
    argv = [str(launcher)]
    if key_file:
        argv += ["--key-file", str(key_file)]
    return argv


def sidecar_env(source: dict, *, node_bin: str | None) -> dict:
    env = {name: source[name] for name in ENV_WHITELIST if name in source}
    if node_bin:
        env["CURSOR_SDK_NODE"] = node_bin
    return env


def _redactor(key_file) -> Callable[[str], str]:
    secret = ""
    if key_file:
        try:
            secret = Path(key_file).read_text(encoding="utf-8").strip()
        except OSError:
            secret = ""
    if not secret:
        return str
    return lambda text: str(text).replace(secret, "<redacted>")


def _failure(code: str, message: str, *, fallback: bool = True) -> SdkOutcome:
    return SdkOutcome(False, "", code, fallback, None, None, None, (), message)


def _parse_lines(stdout: str) -> list[dict]:
    lines = []
    for raw in stdout.splitlines():
        try:
            lines.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return [line for line in lines if isinstance(line, dict)]


def _outcome_from(lines: list[dict], stderr: str) -> SdkOutcome:
    final = lines[-1] if lines else None
    events = tuple(lines[:-1])
    if final is None or final.get("type") not in ("result", "error"):
        return _failure("SDK_ERROR", stderr.strip()[-500:] or "el sidecar no devolvió resultado")
    if final["type"] == "error":
        return SdkOutcome(False, "", final.get("code", "SDK_ERROR"), bool(final.get("fallback", True)), None, None, None, events, final.get("message", ""))
    return SdkOutcome(True, final.get("text", ""), None, False, final.get("usage"), final.get("run_id"), final.get("duration_ms"), events)


def _redacted(outcome: SdkOutcome, redact: Callable[[str], str]) -> SdkOutcome:
    return SdkOutcome(
        outcome.ok, redact(outcome.text), outcome.code, outcome.fallback, outcome.usage, outcome.run_id,
        outcome.duration_ms, tuple(json.loads(redact(json.dumps(e))) for e in outcome.events), redact(outcome.message),
    )


class CursorSdkAdapter:
    def __init__(self, launcher, *, key_file=None, node_bin: str | None = None, environ: dict | None = None, grace_s: float = DEFAULT_GRACE_S):
        self.launcher = Path(launcher)
        self.key_file = key_file
        self.node_bin = node_bin
        self.environ = environ
        self.grace_s = grace_s

    def run(self, prompt: str, *, cwd: str, timeout_s: float = DEFAULT_TIMEOUT_S, **options) -> SdkOutcome:
        redact = _redactor(self.key_file)
        if not self.launcher.exists():
            return _failure("SDK_MISSING", "no está el sidecar cursor-sdk")
        request = sdk_request(prompt, cwd=cwd, timeout_s=timeout_s, **options)
        try:
            done = subprocess.run(
                sidecar_argv(self.launcher, self.key_file),
                input=json.dumps(request),
                capture_output=True,
                text=True,
                timeout=timeout_s + self.grace_s,
                env=sidecar_env(self._source_env(), node_bin=self.node_bin),
                cwd=cwd,
            )
        except subprocess.TimeoutExpired:
            return _failure("TIMEOUT", f"el sidecar no terminó en {timeout_s + self.grace_s:.1f} s")
        except OSError as error:
            return _failure("SDK_MISSING", redact(str(error)))
        return _redacted(_outcome_from(_parse_lines(done.stdout), redact(done.stderr)), redact)

    def steer(self, inbox, text: str) -> None:
        with Path(inbox).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"text": text}, ensure_ascii=False) + "\n")

    def _source_env(self) -> dict:
        if self.environ is not None:
            return dict(self.environ)
        return dict(os.environ)


def run_with_fallback(sdk: CursorSdkAdapter | None, cursor_agent: Callable[..., str], prompt: str, **options) -> ChatResult:
    if sdk is None:
        return ChatResult("cursor-agent", cursor_agent(prompt, **options), None)
    outcome = sdk.run(prompt, **options)
    if outcome.ok or not outcome.fallback:
        return ChatResult("cursor-sdk", outcome.text, outcome)
    return ChatResult("cursor-agent", cursor_agent(prompt, **options), outcome)


DEFAULT_LAUNCHER = Path("adapters") / "cursor_sdk" / "bin" / "cursor-sdk-sidecar"


def adapter_from_config(raw: dict, repo_root) -> CursorSdkAdapter | None:
    settings = raw.get("cursor_sdk") or {}
    if settings.get("enabled", True) is False:
        return None
    launcher = Path(repo_root) / settings.get("launcher", DEFAULT_LAUNCHER)
    if not launcher.exists():
        return None
    key_file = settings.get("api_key_file")
    return CursorSdkAdapter(
        launcher,
        key_file=Path(key_file).expanduser() if key_file else None,
        node_bin=settings.get("node_bin"),
    )

"""Corre un comando en un directorio de job. No llama a un CLI de IA."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class JobRun:
    directory: Path
    exit_code: int | None
    timed_out: bool
    stdout: str
    stderr: str


class JobRunner:
    def __init__(self, jobs_root: Path, clock):
        self.jobs_root = Path(jobs_root)
        self.clock = clock

    def run(self, *, slug: str, command: list[str], cwd: Path, prompt: str, timeout_s: float) -> JobRun:
        raise NotImplementedError("run")

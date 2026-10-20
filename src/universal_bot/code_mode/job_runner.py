"""Corre un comando en un directorio de job. No llama a un CLI de IA."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess


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

    def run(
        self,
        *,
        slug: str,
        command: list[str],
        cwd: Path,
        prompt: str,
        timeout_s: float,
        env: dict | None = None,
        directory: Path | None = None,
    ) -> JobRun:
        started = self.clock.now()
        if directory is None:
            directory = self.jobs_root / f"{started.strftime('%Y%m%dT%H%M%S')}-{slug}"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "prompt.txt").write_text(prompt, encoding="utf-8")
        stdout, stderr, exit_code, timed_out = _execute(command, cwd, timeout_s, env)
        (directory / "stdout").write_text(stdout, encoding="utf-8")
        (directory / "stderr").write_text(stderr, encoding="utf-8")
        meta = {
            "command": list(command),
            "cwd": str(cwd),
            "start": started.isoformat(),
            "end": self.clock.now().isoformat(),
            "exit_code": exit_code,
            "timed_out": timed_out,
        }
        (directory / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        return JobRun(directory, exit_code, timed_out, stdout, stderr)


def _execute(
    command: list[str],
    cwd: Path,
    timeout_s: float,
    env: dict | None,
) -> tuple[str, str, int | None, bool]:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
        env=env,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        return stdout or "", stderr or "", None, True
    return stdout or "", stderr or "", process.returncode, False

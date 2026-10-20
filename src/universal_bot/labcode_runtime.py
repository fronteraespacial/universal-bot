"""Runtime de modo código contra el spool del puente. No abre Discord."""

from __future__ import annotations

from pathlib import Path


def run_once(spool: Path, *, db_path: Path, clock, on_job=None, role_lookup=None) -> dict:
    raise NotImplementedError("run_once")


def main(argv: list[str] | None = None) -> int:
    raise NotImplementedError("main")


if __name__ == "__main__":
    raise SystemExit(main())

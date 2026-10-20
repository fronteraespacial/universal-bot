"""El repo público no versiona ids de Discord ni paths internos."""

from pathlib import Path
import re
import subprocess

import pytest

# Armados por partes: el fuente de este test no puede contener los patrones.
FORBIDDEN_PATTERNS = (
    re.compile(r"\b\d{17,20}\b"),
    "/work" + "space/",
    "/home/" + "box",
)

# Heredados de origin/main. No son de este trabajo y esta rama no los edita.
INHERITED_EXCEPTIONS = (
    "AGENTS.md",
    "docs/architecture-review-codex-astra.md",
    "tests/test_config.py",
    "tests/test_progress_contract.py",
)


def scan_text(text: str) -> list[str]:
    hits = []
    for pattern in FORBIDDEN_PATTERNS:
        if isinstance(pattern, re.Pattern):
            if pattern.search(text):
                hits.append(pattern.pattern)
        elif pattern in text:
            hits.append(pattern)
    return hits


def tracked_files(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    raw = result.stdout.decode("utf-8")
    return [name for name in raw.split("\0") if name]


def violations(root: Path) -> list[str]:
    found = []
    for name in tracked_files(root):
        if name in INHERITED_EXCEPTIONS:
            continue
        path = root / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_bytes().decode("utf-8", errors="replace")
        hits = scan_text(text)
        if hits:
            found.append(f"{name}: {hits[0]}")
    return found


def test_tracked_files_have_no_internal_data():
    root = Path(__file__).resolve().parents[1]
    found = violations(root)
    assert found == []


@pytest.mark.parametrize(
    "payload",
    (
        "9" * 17,
        "9" * 20,
        "/work" + "space/fe-bot-discord",
        "/home/" + "box/.local/bin/grok",
    ),
)
def test_scanner_flags_a_planted_file(tmp_path, payload):
    planted = tmp_path / "nota.txt"
    planted.write_text(f"dato {payload}\n", encoding="utf-8")
    assert scan_text(planted.read_text(encoding="utf-8"))


def test_scanner_accepts_short_ids_and_placeholders(tmp_path):
    planted = tmp_path / "nota.txt"
    planted.write_text("canal 100 usuario 200 path <repo>/<tmp>\n", encoding="utf-8")
    assert scan_text(planted.read_text(encoding="utf-8")) == []


def test_inherited_files_are_the_only_exceptions():
    assert INHERITED_EXCEPTIONS == (
        "AGENTS.md",
        "docs/architecture-review-codex-astra.md",
        "tests/test_config.py",
        "tests/test_progress_contract.py",
    )

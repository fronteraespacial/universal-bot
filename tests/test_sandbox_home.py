"""El lab ve un HOME vacío: solo la config del CLI, en copia efímera (overlay) que no toca el host."""

from pathlib import Path
import shutil
import subprocess

import pytest

from universal_bot.code_mode.lab_runner import LabRunner, ResolvedRoute
from universal_bot.code_mode.sandbox import bwrap_command, cli_mounts
from universal_bot.code_mode.clock import FakeClock
from tests.test_lab_runner import T0

RO = [
    "--ro-bind", "/usr", "/usr",
    "--ro-bind", "/bin", "/bin",
    "--ro-bind", "/lib", "/lib",
    "--ro-bind", "/lib64", "/lib64",
    "--ro-bind", "/etc", "/etc",
]


def test_home_is_a_tmpfs_with_overlays_and_exact_args():
    command = bwrap_command(
        "/lab", ["tool", "x"], allow_network=True, ro_binds=(("/h/.app", "/h/.app"),), home="/h", overlays=("/h/.tool",)
    )
    assert command == [
        "bwrap", *RO, "--tmpfs", "/tmp", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/h",
        "--ro-bind", "/h/.app", "/h/.app",
        "--overlay-src", "/h/.tool", "--tmp-overlay", "/h/.tool",
        "--bind", "/lab", "/lab", "--unshare-all", "--share-net",
        "--die-with-parent", "--chdir", "/lab", "--setenv", "HOME", "/h", "--", "tool", "x",
    ]


def _home(tmp_path):
    home = tmp_path / "home"
    for name in (".grok", ".cursor", ".config/cursor", ".local/share/cursor-agent", ".opencode",
                 ".local/share/opencode", ".config/opencode"):
        (home / name).mkdir(parents=True)
    return home


@pytest.mark.parametrize(
    ("cli", "ro", "overlays"),
    (
        ("grok", (), (".grok",)),
        ("cursor-agent", (".local/share/cursor-agent",), (".cursor", ".config/cursor")),
        ("opencode", (".opencode",), (".local/share/opencode", ".config/opencode")),
        ("otro", (), ()),
    ),
)
def test_cli_mounts_per_cli(tmp_path, cli, ro, overlays):
    home = _home(tmp_path)
    binds, layers = cli_mounts(cli, home)
    assert binds == tuple((str(home / name), str(home / name)) for name in ro)
    assert layers == tuple(str(home / name) for name in overlays)


def test_missing_dirs_are_skipped(tmp_path):
    assert cli_mounts("cursor-agent", tmp_path) == ((), ())


def test_lab_runner_uses_the_masked_home_and_the_real_binary(tmp_path):
    home = _home(tmp_path)
    binary = home / ".grok" / "downloads" / "grok-bin"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    runner = LabRunner(clock=FakeClock(T0), lab_root=tmp_path / "labs", home=home, which=lambda name: str(binary))
    folder = tmp_path / "labs" / "x"
    folder.mkdir(parents=True)
    command = runner._command(ResolvedRoute("grok", "grok-4.7", "medium"), folder, "lab", "p")
    joined = " ".join(command)
    assert f"--tmpfs {home} " in joined
    assert f"--overlay-src {home / '.grok'} --tmp-overlay {home / '.grok'}" in joined
    assert f"--setenv HOME {home} " in joined
    assert f"--ro-bind {home / '.grok'}" not in joined
    assert command[command.index("--") + 1] == str(binary)


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="sin bwrap")
def test_real_bwrap_masks_home_and_discards_overlay_writes(tmp_path):
    home = tmp_path / "home"
    (home / ".tool").mkdir(parents=True)
    (home / ".tool" / "auth").write_text("tok", encoding="utf-8")
    (home / ".secrets").mkdir()
    (home / ".secrets" / "key").write_text("hidden", encoding="utf-8")
    lab = tmp_path / "lab"
    lab.mkdir()
    script = (
        "import os,sys\n"
        "h=os.environ['HOME']\n"
        "print(open(h+'/.tool/auth').read())\n"
        "print(os.path.exists(h+'/.secrets/key'))\n"
        "open(h+'/.tool/new','w').write('x')\n"
        "print(os.path.exists(h+'/.tool/new'))\n"
    )
    command = bwrap_command(str(lab), ["python3", "-c", script], home=str(home), overlays=(str(home / ".tool"),))
    run = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
    assert run.returncode == 0, run.stderr
    assert run.stdout.splitlines() == ["tok", "False", "True"]
    assert not (home / ".tool" / "new").exists()

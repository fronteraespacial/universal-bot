"""bwrap aísla el lab: args exactos y un proceso real si el binario está."""

from pathlib import Path
import shutil
import subprocess

import pytest

from universal_bot.code_mode.sandbox import bwrap_command
from universal_bot.labcode_runtime import main

LAB = "/lab"
INNER = ["python3", "-c", "print(1)"]
RO = [
    "--ro-bind", "/usr", "/usr",
    "--ro-bind", "/bin", "/bin",
    "--ro-bind", "/lib", "/lib",
    "--ro-bind", "/lib64", "/lib64",
    "--ro-bind", "/etc", "/etc",
]


def _expected(labdir: str, inner: list[str], *, allow_network: bool, ro_binds=()) -> list[str]:
    command = ["bwrap", *RO, "--tmpfs", "/tmp"]
    for src, dst in ro_binds:
        command.extend(["--ro-bind", src, dst])
    command.extend(["--bind", labdir, labdir, "--unshare-all"])
    if allow_network:
        command.append("--share-net")
    command.extend(["--die-with-parent", "--chdir", labdir, "--setenv", "HOME", labdir, "--", *inner])
    return command


@pytest.mark.parametrize(
    ("allow_network", "ro_binds"),
    (
        (False, ()),
        (True, ()),
        (True, (("/opt/grok", "/opt/grok"), ("/opt/grok-home", "/opt/grok-home"))),
        (True, (("/opt/cursor", "/opt/cursor"), ("/opt/cursor-cfg", "/opt/cursor-cfg"))),
    ),
)
def test_bwrap_args_match_the_table(allow_network, ro_binds):
    assert bwrap_command(LAB, INNER, allow_network=allow_network, ro_binds=ro_binds) == _expected(
        LAB, INNER, allow_network=allow_network, ro_binds=ro_binds
    )


def test_lab_allow_network_flag_reaches_the_runner(tmp_path, monkeypatch):
    seen = {}

    class Spy:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    monkeypatch.setenv("UBLAB_CONFIG", "")
    monkeypatch.setattr("universal_bot.code_mode.lab_runner.LabRunner", Spy)
    try:
        main(
            [
                "--spool",
                str(tmp_path / "spool"),
                "--once",
                "--db",
                str(tmp_path / "mode.sqlite"),
                "--lab-allow-network",
            ]
        )
    except SystemExit:
        pass
    assert seen.get("allow_network") is True


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="sin bwrap")
def test_real_bwrap_hides_outside_files_and_blocks_sockets(tmp_path):
    lab = tmp_path / "lab"
    lab.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("hidden", encoding="utf-8")
    script = (
        "import socket,sys\n"
        "p=sys.argv[1]\n"
        "try:\n"
        "    open(p).read()\n"
        "    print('READ')\n"
        "except OSError:\n"
        "    print('NOREAD')\n"
        "open('inside.txt','w').write('ok')\n"
        "print(open('inside.txt').read().strip())\n"
        "try:\n"
        "    s=socket.socket()\n"
        "    s.settimeout(1)\n"
        "    s.connect(('1.1.1.1', 443))\n"
        "    print('NET')\n"
        "except OSError:\n"
        "    print('NONET')\n"
    )
    command = bwrap_command(str(lab), ["python3", "-c", script, str(secret)], allow_network=False)
    run = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
    assert run.returncode == 0
    assert run.stdout.splitlines() == ["NOREAD", "ok", "NONET"]
    assert secret.read_text(encoding="utf-8") == "hidden"

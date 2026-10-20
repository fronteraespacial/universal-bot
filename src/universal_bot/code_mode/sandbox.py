"""Arma el comando bwrap del lab. No limita hosts: la red se comparte entera o no se comparte."""

from __future__ import annotations

from pathlib import Path

_RO_ROOTS = ("/usr", "/bin", "/lib", "/lib64", "/etc")


def bwrap_command(labdir, inner, *, allow_network: bool = False, ro_binds=()) -> list[str]:
    folder = str(labdir)
    command = ["bwrap"]
    for root in _RO_ROOTS:
        command.extend(["--ro-bind", root, root])
    command.extend(["--tmpfs", "/tmp"])
    for src, dst in ro_binds:
        command.extend(["--ro-bind", str(src), str(dst)])
    command.extend(["--bind", folder, folder, "--unshare-all"])
    if allow_network:
        command.append("--share-net")
    command.extend(["--die-with-parent", "--chdir", folder, "--setenv", "HOME", folder, "--"])
    command.extend(str(part) for part in inner)
    return command


def cli_ro_binds(cli: str, home: Path, binary: Path | None = None) -> tuple[tuple[str, str], ...]:
    """Binds de solo lectura del binario y de la config del CLI. La red no se puede acotar por host."""
    sources: list[Path] = []
    if binary is not None:
        sources.append(Path(binary))
    if cli == "grok":
        sources.append(Path(home) / ".grok")
    elif cli == "cursor-agent":
        sources.append(Path(home) / ".cursor")
        sources.append(Path(home) / ".config" / "cursor")
    found = []
    for source in sources:
        if source.exists():
            found.append((str(source), str(source)))
    return tuple(found)


def cli_mounts(cli: str, home: Path, binary: Path | None = None):
    raise NotImplementedError

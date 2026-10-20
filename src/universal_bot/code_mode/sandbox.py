"""Arma el comando bwrap del lab. No limita hosts: la red se comparte entera o no se comparte."""

from __future__ import annotations

from pathlib import Path

_RO_ROOTS = ("/usr", "/bin", "/lib", "/lib64", "/etc")


def bwrap_command(labdir, inner, *, allow_network: bool = False, ro_binds=(), home=None, overlays=()) -> list[str]:
    """Sin `home` el HOME es el lab. Con `home`, ese path es un tmpfs vacío con solo los overlays del CLI."""
    folder = str(labdir)
    command = ["bwrap"]
    for root in _RO_ROOTS:
        command.extend(["--ro-bind", root, root])
    command.extend(["--tmpfs", "/tmp"])
    if home is not None:
        command.extend(["--dev", "/dev", "--proc", "/proc", "--tmpfs", str(home)])
    for src, dst in ro_binds:
        command.extend(["--ro-bind", str(src), str(dst)])
    for layer in overlays:
        command.extend(["--overlay-src", str(layer), "--tmp-overlay", str(layer)])
    command.extend(["--bind", folder, folder, "--unshare-all"])
    if allow_network:
        command.append("--share-net")
    command.extend(["--die-with-parent", "--chdir", folder, "--setenv", "HOME", str(home) if home is not None else folder, "--"])
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


_CLI_DIRS = {
    "grok": ((), (".grok",)),
    "cursor-agent": ((".local/share/cursor-agent",), (".cursor", ".config/cursor")),
    "opencode": ((".opencode",), (".local/share/opencode", ".config/opencode")),
}


def cli_mounts(cli: str, home: Path, binary: Path | None = None):
    """Binds ro y overlays efímeros del CLI bajo un HOME enmascarado. Lo que escribe el CLI se descarta."""
    ro_names, overlay_names = _CLI_DIRS.get(cli, ((), ()))
    base = Path(home)
    binds = tuple((str(base / n), str(base / n)) for n in ro_names if (base / n).exists())
    layers = tuple(str(base / n) for n in overlay_names if (base / n).exists())
    if binary is not None:
        real = Path(binary)
        covered = any(str(real).startswith(src + "/") for src, _ in binds) or any(
            str(real).startswith(layer + "/") for layer in layers
        )
        if real.exists() and not covered and not str(real).startswith(("/usr/", "/bin/")):
            binds = binds + ((str(real), str(real)),)
    return binds, layers

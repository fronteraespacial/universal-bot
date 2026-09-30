"""Configuration loader, schema validator, and permission enforcement for Universal Bot."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import os
import sys

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib
    except ImportError:
        raise RuntimeError("tomllib is required (Python 3.11+ or tomli installed)")


@dataclass
class MetaConfig:
    instance_name: str
    host_os: str = "auto"
    host_role: str = "vps"
    timezone: str = "UTC"


@dataclass
class DiscordConfig:
    guild_id: str
    bot_id: str
    allowlist_ids: List[str] = field(default_factory=list)
    allowed_channel_ids: List[str] = field(default_factory=list)
    auto_channels: List[str] = field(default_factory=list)
    allow_dm: bool = False
    message_content_intent: bool = True


@dataclass
class PathsConfig:
    instance_dir: Path
    state_dir: Path
    jobs_dir: Path
    logs_dir: Path
    workspace_dir: Path
    secrets_file: Path
    lock_root: Path


@dataclass
class RuntimeConfig:
    python_cmd: List[str] = field(default_factory=lambda: [sys.executable])
    default_brain: str = ""
    timeout_long_s: int = 1800
    shutdown_grace_s: int = 60
    max_concurrent_jobs: int = 2
    max_pending_jobs: int = 20
    progress_interval_s: int = 120
    progress_freshness_s: int = 180
    watch_interval_s: int = 60


@dataclass
class CliAdapterConfig:
    enabled: bool = False
    command: List[str] = field(default_factory=list)
    auth_mode: str = "existing"
    probe_timeout_s: int = 5


@dataclass
class InstanceConfig:
    schema_version: int
    meta: MetaConfig
    discord: DiscordConfig
    paths: PathsConfig
    runtime: RuntimeConfig
    cli: Dict[str, CliAdapterConfig] = field(default_factory=dict)
    features: Dict[str, bool] = field(default_factory=dict)
    secrets: Dict[str, str] = field(default_factory=dict)

    def is_user_authorized(self, author_id: str) -> bool:
        """Deny-by-default: If allowlist_ids is empty, NO ONE is authorized."""
        if not self.discord.allowlist_ids:
            return False
        return str(author_id) in {str(uid) for uid in self.discord.allowlist_ids}

    def is_channel_allowed(self, channel_id: str, parent_channel_id: Optional[str] = None) -> bool:
        """Checks if a channel or its thread parent is in allowed_channel_ids if configured."""
        if not self.discord.allowed_channel_ids:
            return True
        allowed = {str(cid) for cid in self.discord.allowed_channel_ids}
        if str(channel_id) in allowed:
            return True
        if parent_channel_id and str(parent_channel_id) in allowed:
            return True
        return False

    def is_execution_allowed(
        self,
        author_id: str,
        channel_id: str,
        guild_id: Optional[str] = None,
        is_dm: bool = False,
        parent_channel_id: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Strict authorization gate before doing any work or context retrieval."""
        if is_dm and not self.discord.allow_dm:
            return False, "DM execution is not allowed"

        if guild_id and str(guild_id) != str(self.discord.guild_id):
            return False, f"Guild {guild_id} does not match authorized guild {self.discord.guild_id}"

        if not self.is_channel_allowed(channel_id, parent_channel_id):
            return False, f"Channel {channel_id} is not in allowed channels"

        if not self.is_user_authorized(author_id):
            return False, f"User {author_id} is not in allowlist (deny-by-default active)"

        return True, "authorized"


def parse_secrets_env(env_path: Path) -> Dict[str, str]:
    """Safely parse a .env file without eval or shell interpolation."""
    secrets: Dict[str, str] = {}
    if not env_path.is_file():
        return secrets

    try:
        content = env_path.read_text(encoding="utf-8")
    except Exception:
        return secrets

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        if key:
            secrets[key] = val
    return secrets


def load_instance_config(config_path: Path | str) -> InstanceConfig:
    """Load and validate an instance.toml file, resolving all relative paths against its directory."""
    path = Path(config_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Configuration file not found: {path}")

    instance_dir = path.parent

    with open(path, "rb") as f:
        data = tomllib.load(f)

    schema_version = int(data.get("schema_version", 1))

    # Meta
    meta_raw = data.get("meta", {})
    meta = MetaConfig(
        instance_name=str(meta_raw.get("instance_name", instance_dir.name)),
        host_os=str(meta_raw.get("host_os", "auto")),
        host_role=str(meta_raw.get("host_role", "vps")),
        timezone=str(meta_raw.get("timezone", "UTC")),
    )

    # Discord
    dc_raw = data.get("discord", {})
    allowlist = [str(x) for x in dc_raw.get("allowlist_ids", []) if str(x) != "REPLACE_ADMIN_USER_ID"]
    allowed_channels = [str(x) for x in dc_raw.get("allowed_channel_ids", [])]
    auto_channels = [str(x) for x in dc_raw.get("auto_channels", [])]

    discord = DiscordConfig(
        guild_id=str(dc_raw.get("guild_id", "")),
        bot_id=str(dc_raw.get("bot_id", "")),
        allowlist_ids=allowlist,
        allowed_channel_ids=allowed_channels,
        auto_channels=auto_channels,
        allow_dm=bool(dc_raw.get("allow_dm", False)),
        message_content_intent=bool(dc_raw.get("message_content_intent", True)),
    )

    # Paths resolution relative to instance_dir
    p_raw = data.get("paths", {})

    def _resolve(key: str, default: str) -> Path:
        raw_val = p_raw.get(key, default)
        p = Path(os.path.expanduser(str(raw_val)))
        if not p.is_absolute():
            p = instance_dir / p
        return p.resolve()

    paths = PathsConfig(
        instance_dir=instance_dir,
        state_dir=_resolve("state_dir", "./state"),
        jobs_dir=_resolve("jobs_dir", "./state/jobs"),
        logs_dir=_resolve("logs_dir", "./state/logs"),
        workspace_dir=_resolve("workspace_dir", "./workspaces"),
        secrets_file=_resolve("secrets_file", "./secrets.env"),
        lock_root=_resolve("lock_root", "./state/locks"),
    )

    # Runtime
    rt_raw = data.get("runtime", {})
    py_val = rt_raw.get("python", rt_raw.get("python_cmd", [sys.executable]))
    if isinstance(py_val, str):
        # Support string format if space-split or single binary
        python_cmd = py_val.split()
    elif isinstance(py_val, list):
        python_cmd = [str(x) for x in py_val]
    else:
        python_cmd = [sys.executable]

    runtime = RuntimeConfig(
        python_cmd=python_cmd,
        default_brain=str(rt_raw.get("default_brain", "")),
        timeout_long_s=max(1, int(rt_raw.get("timeout_long_s", 1800))),
        shutdown_grace_s=max(1, int(rt_raw.get("shutdown_grace_s", 60))),
        max_concurrent_jobs=max(1, int(rt_raw.get("max_concurrent_jobs", 2))),
        max_pending_jobs=max(1, int(rt_raw.get("max_pending_jobs", 20))),
        progress_interval_s=max(1, int(rt_raw.get("progress_interval_s", 120))),
        progress_freshness_s=max(1, int(rt_raw.get("progress_freshness_s", 180))),
        watch_interval_s=max(1, int(rt_raw.get("watch_interval_s", 60))),
    )

    # CLI adapters
    cli_raw = data.get("cli", {})
    cli_adapters: Dict[str, CliAdapterConfig] = {}
    for brain_name, raw_cfg in cli_raw.items():
        if isinstance(raw_cfg, bool):
            cli_adapters[brain_name] = CliAdapterConfig(enabled=raw_cfg, command=[brain_name])
        elif isinstance(raw_cfg, dict):
            cmd = raw_cfg.get("command", [brain_name])
            if isinstance(cmd, str):
                cmd = cmd.split()
            cli_adapters[brain_name] = CliAdapterConfig(
                enabled=bool(raw_cfg.get("enabled", False)),
                command=list(cmd),
                auth_mode=str(raw_cfg.get("auth_mode", "existing")),
                probe_timeout_s=int(raw_cfg.get("probe_timeout_s", 5)),
            )

    # Features
    features_raw = data.get("features", {})
    features = {str(k): bool(v) for k, v in features_raw.items()}

    # Secrets
    secrets = parse_secrets_env(paths.secrets_file)

    return InstanceConfig(
        schema_version=schema_version,
        meta=meta,
        discord=discord,
        paths=paths,
        runtime=runtime,
        cli=cli_adapters,
        features=features,
        secrets=secrets,
    )

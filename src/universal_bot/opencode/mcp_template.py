"""Per-bot OpenCode MCP + skill templates (no global ~/.config/opencode)."""

from __future__ import annotations

import json
from pathlib import Path
from string import Template


_OPENCODE_JSON = Template(
    """{
  "$$schema": "https://opencode.ai/config.json",
  "model": "$default_model",
  "small_model": "$default_model",
  "mcp": {
    "$mcp_name": {
      "type": "local",
      "command": ["bash", "$run_mcp_path"],
      "enabled": true,
      "timeout": 15000,
      "environment": {
        "PATH": "$path_env"
      }
    }
  },
  "permission": {
    "bash": "allow",
    "edit": "allow",
    "write": "allow",
    "read": "allow",
    "grep": "allow",
    "glob": "allow",
    "list": "allow",
    "skill": {
      "*": "allow"
    },
    "webfetch": "allow"
  }
}
"""
)

_RUN_MCP_SH = Template(
    """#!/usr/bin/env bash
# Per-bot MCP wrapper. Paths are instance-local — do not point at another bot.
set -euo pipefail
cd "$bot_root"
exec "$python_bin" "$mcp_server"
"""
)

_PACK_RULES = Template(
    """---
name: $skill_name
description: Canonical shared rules for this bot pack. Load at the start of any Discord/OpenCode request.
compatibility: opencode
---

# $skill_name

Read and follow `$agents_md`.

Timezone: $timezone. Clock: MCP tool `get_current_time` on server `$mcp_name`.

Pack workflow skills live under the host workflows directory — open them with read when a request names them.

Discord/pack tools: use MCP `$mcp_name` (do not invent channels or times).
"""
)

_GET_TIME = Template(
    """---
name: get-time
description: Obtain exact time in $timezone via MCP $mcp_name get_current_time (never invent the clock).
compatibility: opencode
---

# get-time

When asked for the time, date, or "what time is it":

1. Call MCP tool `get_current_time` on server `$mcp_name`.
2. Answer with that result in zone $timezone.
3. Do not invent or use the model clock.
"""
)


def render_opencode_json(
    *,
    bot_slug: str,
    run_mcp_path: str,
    path_env: str,
    default_model: str = "opencode-go/deepseek-v4.1-flash",
    mcp_name: str | None = None,
) -> str:
    """Render a per-bot ``opencode.json`` (MCP via run_mcp.sh wrapper)."""
    name = mcp_name or bot_slug
    text = _OPENCODE_JSON.substitute(
        default_model=default_model,
        mcp_name=name,
        run_mcp_path=run_mcp_path,
        path_env=path_env,
    )
    # Validate JSON shape (no secrets).
    json.loads(text)
    return text


def render_run_mcp_sh(
    *,
    bot_root: str,
    python_bin: str,
    mcp_server: str,
) -> str:
    """Render ``run_mcp.sh`` that execs the bot's MCP server in its venv."""
    return _RUN_MCP_SH.substitute(
        bot_root=bot_root,
        python_bin=python_bin,
        mcp_server=mcp_server,
    )


def render_pack_rules_skill(
    *,
    bot_slug: str,
    agents_md: str,
    timezone: str = "America/Buenos_Aires",
    mcp_name: str | None = None,
) -> str:
    skill_name = f"{bot_slug}-pack-rules"
    return _PACK_RULES.substitute(
        skill_name=skill_name,
        agents_md=agents_md,
        timezone=timezone,
        mcp_name=mcp_name or bot_slug,
    )


def render_get_time_skill(
    *,
    bot_slug: str,
    timezone: str = "America/Buenos_Aires",
    mcp_name: str | None = None,
) -> str:
    return _GET_TIME.substitute(
        timezone=timezone,
        mcp_name=mcp_name or bot_slug,
    )


def write_bot_opencode_layout(
    dest: Path,
    *,
    bot_slug: str,
    bot_root: str,
    python_bin: str,
    mcp_server: str,
    path_env: str,
    agents_md: str,
    timezone: str = "America/Buenos_Aires",
) -> dict[str, Path]:
    """Write opencode.json, run_mcp.sh, and .opencode/skills into ``dest``.

    ``dest`` is the per-bot config dir (UB_OPENCODE_CONFIG_DIR), not
    ``~/.config/opencode``.
    """
    dest = Path(dest)
    skills = dest / ".opencode" / "skills"
    pack_dir = skills / f"{bot_slug}-pack-rules"
    time_dir = skills / "get-time"
    pack_dir.mkdir(parents=True, exist_ok=True)
    time_dir.mkdir(parents=True, exist_ok=True)

    run_mcp = dest / "run_mcp.sh"
    run_mcp.write_text(
        render_run_mcp_sh(
            bot_root=bot_root, python_bin=python_bin, mcp_server=mcp_server
        ),
        encoding="utf-8",
    )
    run_mcp.chmod(0o755)

    oc_json = dest / "opencode.json"
    oc_json.write_text(
        render_opencode_json(
            bot_slug=bot_slug,
            run_mcp_path=str(run_mcp),
            path_env=path_env,
            mcp_name=bot_slug,
        ),
        encoding="utf-8",
    )

    pack_skill = pack_dir / "SKILL.md"
    pack_skill.write_text(
        render_pack_rules_skill(
            bot_slug=bot_slug, agents_md=agents_md, timezone=timezone, mcp_name=bot_slug
        ),
        encoding="utf-8",
    )
    time_skill = time_dir / "SKILL.md"
    time_skill.write_text(
        render_get_time_skill(bot_slug=bot_slug, timezone=timezone, mcp_name=bot_slug),
        encoding="utf-8",
    )
    return {
        "opencode_json": oc_json,
        "run_mcp_sh": run_mcp,
        "pack_rules": pack_skill,
        "get_time": time_skill,
    }

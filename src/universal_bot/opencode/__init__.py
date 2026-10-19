"""OpenCode V2 helpers: shared serve, PTY run, Free remap, MCP templates.

Env prefix: UB_OPENCODE_*. Reference packs that keep FE_OPENCODE_* aliases
must map those locally; this library only reads UB_OPENCODE_*.
"""

from universal_bot.opencode.env import OpenCodeEnv, load_opencode_env
from universal_bot.opencode.models import (
    DEFAULT_FREE_MODEL,
    CLI_ONLY_FREE_MODELS,
    effort_to_variant,
    format_go_model,
    format_model_arg,
    remap_free_model,
)
from universal_bot.opencode.serve import (
    ServeHealth,
    healthcheck,
    lookup_serve_password,
    restart_serve_hint,
    serve_url,
)
from universal_bot.opencode.run import (
    RunPlan,
    build_run_argv,
    plan_run,
    prepare_run_env,
)
from universal_bot.opencode.pty_spawn import (
    PtyUnavailable,
    pty_available,
    spawn_with_pty,
)
from universal_bot.opencode.mcp_template import (
    render_get_time_skill,
    render_opencode_json,
    render_pack_rules_skill,
    render_run_mcp_sh,
    write_bot_opencode_layout,
)

__all__ = [
    "OpenCodeEnv",
    "load_opencode_env",
    "DEFAULT_FREE_MODEL",
    "CLI_ONLY_FREE_MODELS",
    "effort_to_variant",
    "format_go_model",
    "format_model_arg",
    "remap_free_model",
    "ServeHealth",
    "healthcheck",
    "lookup_serve_password",
    "restart_serve_hint",
    "serve_url",
    "RunPlan",
    "build_run_argv",
    "plan_run",
    "prepare_run_env",
    "PtyUnavailable",
    "pty_available",
    "spawn_with_pty",
    "render_get_time_skill",
    "render_opencode_json",
    "render_pack_rules_skill",
    "render_run_mcp_sh",
    "write_bot_opencode_layout",
]

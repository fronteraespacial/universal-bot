"""Unified progress: one editable trail per job, an optional log, an optional pin.

The host injects a :class:`~universal_bot.unified_progress.transport.DiscordTransport`.
Nothing in this package opens a network connection.
"""

from universal_bot.unified_progress.cli_logs import job_log_embed, post_job_log
from universal_bot.unified_progress.config import (
    CliStyle,
    UnifiedProgressConfig,
    load_unified_progress,
    stop_button_enabled,
)
from universal_bot.unified_progress.quota import (
    bar,
    format_quota_block,
    quota_footer,
    take_snapshot,
)
from universal_bot.unified_progress.quota_pin import pin_enabled, update
from universal_bot.unified_progress.scope import effective_mode, in_scope, payload_in_scope
from universal_bot.unified_progress.stop_control import (
    parse_stop_button_custom_id,
    running_stop_components,
    stop_button_custom_id,
)
from universal_bot.unified_progress.stop_interaction import (
    StopButtonClick,
    StopHandleResult,
    StopOutcome,
    handle_stop_interaction,
    interaction_response,
    parse_stop_button_interaction,
    stop_acl_allowed,
)
from universal_bot.unified_progress.trail import LiveTrail, Trail, push_event
from universal_bot.unified_progress.transport import (
    DiscordTransport,
    MessageMissing,
    RateLimited,
    retry_on_rate_limit,
)

__all__ = [
    "CliStyle",
    "DiscordTransport",
    "LiveTrail",
    "MessageMissing",
    "RateLimited",
    "Trail",
    "UnifiedProgressConfig",
    "bar",
    "effective_mode",
    "format_quota_block",
    "handle_stop_interaction",
    "in_scope",
    "interaction_response",
    "job_log_embed",
    "load_unified_progress",
    "payload_in_scope",
    "pin_enabled",
    "post_job_log",
    "parse_stop_button_custom_id",
    "parse_stop_button_interaction",
    "push_event",
    "quota_footer",
    "retry_on_rate_limit",
    "running_stop_components",
    "stop_acl_allowed",
    "stop_button_custom_id",
    "stop_button_enabled",
    "StopButtonClick",
    "StopHandleResult",
    "StopOutcome",
    "take_snapshot",
    "update",
]

"""Universal Bot: A portable, self-hosted Discord agent gateway and worker."""

from universal_bot.activity import (
    ActivityReport,
    ActivitySignal,
    ActivitySnapshot,
    RealActivityMonitor,
    get_dir_newest_mtime,
    is_pid_alive,
    real_activity_seen,
)
from universal_bot.config import (
    InstanceConfig,
    load_instance_config,
    parse_secrets_env,
)
from universal_bot.contracts import (
    AdapterCapabilities,
    DeliveryStatus,
    JobEvent,
    JobRequest,
    JobResult,
    JobStatus,
    RoutingDecision,
)
from universal_bot.dispatcher import Dispatcher
from universal_bot.locks import SingletonLock
from universal_bot.redact import (
    ChunkStreamRedactor,
    RedactingFilter,
    RedactingFormatter,
    SecretRedactor,
)
from universal_bot.store import JobStore

__version__ = "0.1.0"

__all__ = [
    "ActivityReport",
    "ActivitySignal",
    "ActivitySnapshot",
    "RealActivityMonitor",
    "get_dir_newest_mtime",
    "is_pid_alive",
    "real_activity_seen",
    "InstanceConfig",
    "load_instance_config",
    "parse_secrets_env",
    "JobStatus",
    "DeliveryStatus",
    "JobRequest",
    "JobResult",
    "JobEvent",
    "AdapterCapabilities",
    "RoutingDecision",
    "JobStore",
    "Dispatcher",
    "SingletonLock",
    "SecretRedactor",
    "RedactingFilter",
    "RedactingFormatter",
    "ChunkStreamRedactor",
]

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

__version__ = "0.1.0"

__all__ = [
    "ActivityReport",
    "ActivitySignal",
    "ActivitySnapshot",
    "RealActivityMonitor",
    "get_dir_newest_mtime",
    "is_pid_alive",
    "real_activity_seen",
]

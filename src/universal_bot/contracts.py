"""Data contracts and schemas for Universal Bot."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional
import time
import uuid


class JobStatus(str, Enum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    INTERRUPTED = "interrupted"

    def is_terminal(self) -> bool:
        return self in {
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
            JobStatus.TIMED_OUT,
            JobStatus.INTERRUPTED,
        }


class DeliveryStatus(str, Enum):
    PENDING = "pending"
    SENDING = "sending"
    DELIVERED = "delivered"
    RETRY_WAIT = "retry_wait"
    DELIVERY_FAILED = "delivery_failed"
    UNCERTAIN = "uncertain"

    def is_terminal(self) -> bool:
        return self in {DeliveryStatus.DELIVERED, DeliveryStatus.DELIVERY_FAILED}


@dataclass
class JobRequest:
    job_id: str
    instance_name: str
    message_id: str
    guild_id: str
    channel_id: str
    author_id: str
    prompt: str
    brain: str
    workspace_dir: str
    thread_id: Optional[str] = None
    created_ts: float = field(default_factory=time.time)
    deadline_ts: float = 0.0

    @classmethod
    def create(
        cls,
        instance_name: str,
        message_id: str,
        guild_id: str,
        channel_id: str,
        author_id: str,
        prompt: str,
        brain: str,
        workspace_dir: str,
        timeout_s: float = 1800.0,
        thread_id: Optional[str] = None,
        job_id: Optional[str] = None,
    ) -> "JobRequest":
        now = time.time()
        return cls(
            job_id=job_id or f"job_{uuid.uuid4().hex[:12]}",
            instance_name=instance_name,
            message_id=str(message_id),
            guild_id=str(guild_id),
            channel_id=str(channel_id),
            thread_id=str(thread_id) if thread_id else None,
            author_id=str(author_id),
            prompt=prompt,
            brain=brain,
            workspace_dir=workspace_dir,
            created_ts=now,
            deadline_ts=now + timeout_s,
        )


@dataclass
class JobResult:
    job_id: str
    status: JobStatus
    exit_code: Optional[int] = None
    output: str = ""
    error: str = ""
    duration_s: float = 0.0
    stdout_bytes: int = 0
    stderr_bytes: int = 0
    completed_ts: float = field(default_factory=time.time)


@dataclass
class JobEvent:
    event_id: str
    job_id: str
    event_type: str
    payload: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)


@dataclass
class AdapterCapabilities:
    headless: bool = True
    structured_output: bool = False
    resume: bool = False
    steering: bool = False
    images: bool = False


@dataclass
class RoutingDecision:
    adapter_name: str
    model: str
    reason: str
    allowed_fallback: bool = False

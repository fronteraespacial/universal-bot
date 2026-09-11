"""Admission, deduplication, capacity management, and FIFO dispatch coordination."""

from typing import Optional, Tuple
import os

from universal_bot.config import InstanceConfig
from universal_bot.contracts import JobRequest, JobResult, JobStatus
from universal_bot.store import JobStore


class Dispatcher:
    """Coordinates admission gates, deduplication, and FIFO job claiming."""

    def __init__(self, config: InstanceConfig, store: JobStore):
        self.config = config
        self.store = store

    def admit_request(
        self,
        author_id: str,
        channel_id: str,
        message_id: str,
        prompt: str,
        brain: str = "",
        guild_id: Optional[str] = None,
        workspace_dir: Optional[str] = None,
        thread_id: Optional[str] = None,
        is_dm: bool = False,
        parent_channel_id: Optional[str] = None,
    ) -> Tuple[Optional[JobRequest], bool, str]:
        """Strict admission gate: checks authorization (deny-by-default), deduplicates, and validates capacity."""
        # 1. Check authorization gate
        allowed, reason = self.config.is_execution_allowed(
            author_id=author_id,
            channel_id=channel_id,
            guild_id=guild_id,
            is_dm=is_dm,
            parent_channel_id=parent_channel_id,
        )
        if not allowed:
            return None, False, f"admission_denied: {reason}"

        # 2. Resolve brain / CLI
        target_brain = brain.strip().lower() if brain else self.config.runtime.default_brain
        if not target_brain:
            # If no default brain is configured, admit into diagnostic mode or fail
            target_brain = "unassigned"

        # 3. Resolve workspace dir
        target_ws = workspace_dir or str(self.config.paths.workspace_dir)

        # 4. Construct JobRequest
        req = JobRequest.create(
            instance_name=self.config.meta.instance_name,
            message_id=str(message_id),
            guild_id=str(guild_id or self.config.discord.guild_id),
            channel_id=str(channel_id),
            thread_id=str(thread_id) if thread_id else None,
            author_id=str(author_id),
            prompt=prompt,
            brain=target_brain,
            workspace_dir=target_ws,
            timeout_s=float(self.config.runtime.timeout_long_s),
        )

        # 5. Atomically admit with deduplication and queue bounds
        admitted_job, was_admitted, store_reason = self.store.admit_job(
            req, max_pending=self.config.runtime.max_pending_jobs
        )

        return admitted_job, was_admitted, store_reason

    def claim_next(self, worker_id: str) -> Optional[JobRequest]:
        """Claim next queued job respecting worker concurrency and FIFO conversation mutex."""
        return self.store.claim_next_job(
            lease_owner=worker_id,
            max_concurrent=self.config.runtime.max_concurrent_jobs,
            enforce_channel_mutex=True,
        )

    def mark_completed(
        self,
        job_id: str,
        status: JobStatus,
        exit_code: Optional[int] = None,
        output: str = "",
        error: str = "",
    ) -> bool:
        """Complete job and release conversation mutex."""
        return self.store.finish_job(
            job_id=job_id,
            status=status,
            exit_code=exit_code,
            output=output,
            error=error,
        )

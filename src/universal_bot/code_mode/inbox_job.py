"""Parser del job.json que deja el puente en el inbox."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from universal_bot.code_mode.models import Location


class InboxJobError(ValueError):
    """El job del inbox no cumple el contrato."""


@dataclass(frozen=True)
class InboxAuthor:
    id: int
    display_name: str


@dataclass(frozen=True)
class InboxJob:
    job_id: str
    instance: str
    source: str
    guild_id: int
    channel_id: int
    thread_id: int | None
    parent_channel_id: int
    message_id: int
    author: InboxAuthor
    author_context: str
    content_raw: str
    prompt: str
    attachments: tuple
    audio_transcripts: tuple
    previous_messages: tuple
    location_key: str
    session_key: str
    created_ts: float
    deadline_ts: float
    button_prefix: str
    reply_to_message_id: int | None
    outbox_dir: str
    answers_dir: str

    @property
    def location(self) -> Location:
        return Location(self.guild_id, self.channel_id, self.thread_id)


@dataclass(frozen=True)
class JobState:
    version: int
    status: str
    updated_ts: float
    summary: str
    active_step: str | None
    error: str | None
    op_ids: tuple[str, ...]


def load_inbox_job(job_dir: Path) -> InboxJob:
    raise NotImplementedError("load_inbox_job")


def write_job_state(job_dir: Path, state: JobState) -> None:
    raise NotImplementedError("write_job_state")

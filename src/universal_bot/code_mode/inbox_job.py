"""Parser del job.json que deja el puente en el inbox."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from universal_bot.code_mode.models import Location

_REQUIRED = (
    "version",
    "job_id",
    "instance",
    "source",
    "guild_id",
    "channel_id",
    "thread_id",
    "parent_channel_id",
    "message_id",
    "author",
    "author_context",
    "content_raw",
    "prompt",
    "attachments",
    "audio_transcripts",
    "previous_messages",
    "location_key",
    "session_key",
    "created_ts",
    "deadline_ts",
    "button_prefix",
    "reply_to_message_id",
    "outbox_dir",
    "answers_dir",
)


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
    directory = Path(job_dir)
    raw = _read_json(directory / "job.json")
    missing = [key for key in _REQUIRED if key not in raw]
    if missing:
        raise InboxJobError(f"falta el campo {missing[0]}")
    if raw["version"] != 1:
        raise InboxJobError("version distinta de 1")
    if raw["instance"] != "fe-labcode":
        raise InboxJobError("instance distinta de fe-labcode")
    if raw["button_prefix"] != "ublab:":
        raise InboxJobError("button_prefix distinto de ublab:")
    if raw["session_key"] != raw["location_key"]:
        raise InboxJobError("session_key distinto de location_key")
    prompt_path = directory / "prompt.txt"
    if not prompt_path.is_file():
        raise InboxJobError("falta prompt.txt")
    prompt_txt = prompt_path.read_text(encoding="utf-8")
    if prompt_txt != raw["prompt"]:
        raise InboxJobError("prompt.txt no coincide con prompt")
    author = raw["author"]
    if not isinstance(author, dict) or "id" not in author or "display_name" not in author:
        raise InboxJobError("falta el campo author")
    return InboxJob(
        job_id=str(raw["job_id"]),
        instance=raw["instance"],
        source=str(raw["source"]),
        guild_id=_num(raw["guild_id"], "guild_id"),
        channel_id=_num(raw["channel_id"], "channel_id"),
        thread_id=_num_or_null(raw["thread_id"], "thread_id"),
        parent_channel_id=_num(raw["parent_channel_id"], "parent_channel_id"),
        message_id=_num(raw["message_id"], "message_id"),
        author=InboxAuthor(_num(author["id"], "author.id"), str(author["display_name"])),
        author_context=str(raw["author_context"]),
        content_raw=str(raw["content_raw"]),
        prompt=str(raw["prompt"]),
        attachments=_as_tuple(raw["attachments"], "attachments"),
        audio_transcripts=_as_tuple(raw["audio_transcripts"], "audio_transcripts"),
        previous_messages=_as_tuple(raw["previous_messages"], "previous_messages"),
        location_key=str(raw["location_key"]),
        session_key=str(raw["session_key"]),
        created_ts=_stamp(raw["created_ts"], "created_ts"),
        deadline_ts=_stamp(raw["deadline_ts"], "deadline_ts"),
        button_prefix=raw["button_prefix"],
        reply_to_message_id=_num_or_null(raw["reply_to_message_id"], "reply_to_message_id"),
        outbox_dir=str(raw["outbox_dir"]),
        answers_dir=str(raw["answers_dir"]),
    )


def write_job_state(job_dir: Path, state: JobState) -> None:
    payload = {
        "version": state.version,
        "status": state.status,
        "updated_ts": state.updated_ts,
        "summary": state.summary,
        "active_step": state.active_step,
        "error": state.error,
        "op_ids": list(state.op_ids),
    }
    (Path(job_dir) / "state.json").write_text(json.dumps(payload), encoding="utf-8")


def _read_json(path: Path) -> dict:
    if not path.is_file():
        raise InboxJobError(f"falta {path.name}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InboxJobError(f"{path.name} inválido") from exc
    if not isinstance(raw, dict):
        raise InboxJobError(f"{path.name} inválido")
    return raw


def _num(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise InboxJobError(f"{field} no es numérico")
    text = str(value)
    if not text.isdigit():
        raise InboxJobError(f"{field} no es numérico")
    return int(text)


def _num_or_null(value: object, field: str) -> int | None:
    if value is None:
        return None
    return _num(value, field)


def _stamp(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InboxJobError(f"{field} no es numérico")
    return float(value)


def _as_tuple(value: object, field: str) -> tuple:
    if not isinstance(value, list):
        raise InboxJobError(f"{field} no es una lista")
    return tuple(value)

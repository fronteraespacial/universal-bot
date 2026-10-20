"""Parser de InboxJob contra el contrato del puente."""

import json
from pathlib import Path

import pytest

from universal_bot.code_mode.inbox_job import InboxJobError, JobState, load_inbox_job, write_job_state
from universal_bot.code_mode.models import Location

CHANNEL = 910001


def sample(**overrides) -> dict:
    payload = {
        "version": 1,
        "job_id": "job-1",
        "instance": "fe-labcode",
        "source": "discord",
        "guild_id": "10",
        "channel_id": str(CHANNEL),
        "thread_id": None,
        "parent_channel_id": str(CHANNEL),
        "message_id": "555",
        "author": {"id": "7", "display_name": "Julian"},
        "author_context": "julian",
        "content_raw": "hola",
        "prompt": "hola",
        "attachments": [],
        "audio_transcripts": [],
        "previous_messages": [{"id": "1", "content": "antes"}],
        "location_key": f"10:{CHANNEL}",
        "session_key": f"10:{CHANNEL}",
        "created_ts": 1000.0,
        "deadline_ts": 2800.0,
        "button_prefix": "ublab:",
        "reply_to_message_id": None,
        "outbox_dir": "/tmp/outbox",
        "answers_dir": "/tmp/answers",
    }
    payload.update(overrides)
    return payload


def dump_job(root: Path, payload: dict, *, prompt_txt: str | None = None) -> Path:
    job_dir = root / f"lc_{payload.get('message_id', 'x')}"
    job_dir.mkdir(parents=True)
    (job_dir / "job.json").write_text(json.dumps(payload), encoding="utf-8")
    if prompt_txt is not None:
        (job_dir / "prompt.txt").write_text(prompt_txt, encoding="utf-8")
    else:
        (job_dir / "prompt.txt").write_text(str(payload.get("prompt", "")), encoding="utf-8")
    return job_dir


def test_loads_job_and_uses_location_key_as_session_location(tmp_path):
    job_dir = dump_job(tmp_path, sample(thread_id="99"))
    job = load_inbox_job(job_dir)
    assert job.job_id == "job-1"
    assert job.instance == "fe-labcode"
    assert job.button_prefix == "ublab:"
    assert job.guild_id == 10
    assert job.channel_id == CHANNEL
    assert job.thread_id == 99
    assert job.message_id == 555
    assert job.author.id == 7
    assert job.author.display_name == "Julian"
    assert job.session_key == job.location_key
    assert job.location == Location(10, CHANNEL, 99)
    assert job.previous_messages == ({"id": "1", "content": "antes"},)
    assert job.reply_to_message_id is None


def test_null_parent_channel_is_allowed(tmp_path):
    job = load_inbox_job(dump_job(tmp_path, sample(parent_channel_id=None)))
    assert job.parent_channel_id is None


def test_accepts_numeric_json_ids(tmp_path):
    payload = sample(guild_id=10, channel_id=CHANNEL, message_id=555, parent_channel_id=CHANNEL)
    payload["author"] = {"id": 7, "display_name": "Julian"}
    job = load_inbox_job(dump_job(tmp_path, payload))
    assert job.guild_id == 10
    assert job.author.id == 7


def test_missing_field_is_a_clear_error(tmp_path):
    payload = sample()
    del payload["job_id"]
    with pytest.raises(InboxJobError, match="job_id"):
        load_inbox_job(dump_job(tmp_path, payload))


def test_wrong_button_prefix_is_rejected(tmp_path):
    with pytest.raises(InboxJobError, match="ublab:"):
        load_inbox_job(dump_job(tmp_path, sample(button_prefix="ub:")))


def test_prompt_txt_must_match(tmp_path):
    with pytest.raises(InboxJobError, match="prompt"):
        load_inbox_job(dump_job(tmp_path, sample(), prompt_txt="otro"))


def test_session_key_must_equal_location_key(tmp_path):
    with pytest.raises(InboxJobError, match="session_key"):
        load_inbox_job(dump_job(tmp_path, sample(session_key="otra")))


def test_wrong_version_or_instance_is_rejected(tmp_path):
    with pytest.raises(InboxJobError, match="version"):
        load_inbox_job(dump_job(tmp_path, sample(version=2)))
    with pytest.raises(InboxJobError, match="fe-labcode"):
        load_inbox_job(dump_job(tmp_path / "b", sample(instance="otro")))


def test_non_numeric_id_is_rejected(tmp_path):
    with pytest.raises(InboxJobError, match="channel_id"):
        load_inbox_job(dump_job(tmp_path, sample(channel_id="abc")))


def test_runtime_owns_state_json(tmp_path):
    job_dir = dump_job(tmp_path, sample())
    state = JobState(
        version=1,
        status="accepted",
        updated_ts=1000.5,
        summary="en curso",
        active_step="02-lab",
        error=None,
        op_ids=("20261020T120000-0001-send",),
    )
    write_job_state(job_dir, state)
    raw = json.loads((job_dir / "state.json").read_text(encoding="utf-8"))
    assert raw["version"] == 1
    assert raw["status"] == "accepted"
    assert raw["updated_ts"] == 1000.5
    assert raw["summary"] == "en curso"
    assert raw["active_step"] == "02-lab"
    assert raw["error"] is None
    assert raw["op_ids"] == ["20261020T120000-0001-send"]

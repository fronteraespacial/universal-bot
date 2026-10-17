"""Gateway-side stop button interaction handling."""

from pathlib import Path

from universal_bot.unified_progress.stop_interaction import (
    StopOutcome,
    handle_stop_interaction,
    parse_stop_button_interaction,
    stop_acl_allowed,
)
from universal_bot.unified_progress.stop_control import stop_button_custom_id
from universal_bot.unified_progress.trail import write_marker


def _component_interaction(custom_id: str, user_id: str = "329811958603972609") -> dict:
    return {
        "type": 3,
        "id": "999",
        "token": "tok",
        "member": {"user": {"id": user_id}},
        "data": {"custom_id": custom_id},
    }


def test_parse_stop_interaction():
    cid = stop_button_custom_id("1560336060888780931", "job-abc")
    click = parse_stop_button_interaction(_component_interaction(cid))
    assert click is not None
    assert click.channel_id == "1560336060888780931"
    assert click.job_id == "job-abc"
    assert click.user_id == "329811958603972609"
    assert parse_stop_button_interaction({"type": 2}) is None


def test_acl_author_and_admin():
    admins = frozenset({"363744726773530625"})
    assert stop_acl_allowed(clicker_id="329811958603972609", marker_author_id="329811958603972609", admin_ids=admins)
    assert stop_acl_allowed(clicker_id="363744726773530625", marker_author_id="111", admin_ids=admins)
    assert not stop_acl_allowed(clicker_id="999", marker_author_id="329811958603972609", admin_ids=admins)
    assert not stop_acl_allowed(clicker_id="999", marker_author_id=None, admin_ids=admins)


def test_handle_denied_and_cancel(tmp_path: Path):
    chan, job = "c1", "j1"
    write_marker(tmp_path, chan, job, "msg1", author_id="329811958603972609")
    cid = stop_button_custom_id(chan, job)
    denied = handle_stop_interaction(
        _component_interaction(cid, user_id="999"),
        state_dir=tmp_path,
        admin_ids=frozenset(),
        cancel_job=lambda _c, _j: True,
    )
    assert denied.outcome == StopOutcome.DENIED
    assert denied.response and "permiso" in denied.response["data"]["content"]

    killed: list[tuple[str, str]] = []

    def _cancel(c: str, j: str) -> bool:
        killed.append((c, j))
        return True

    ok = handle_stop_interaction(
        _component_interaction(cid),
        state_dir=tmp_path,
        admin_ids=frozenset(),
        cancel_job=_cancel,
    )
    assert ok.outcome == StopOutcome.CANCELLED
    assert killed == [(chan, job)]
    assert ok.response and "Cancelado" in ok.response["data"]["content"]

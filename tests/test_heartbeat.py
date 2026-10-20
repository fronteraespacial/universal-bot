"""El heartbeat se toca con el reloj inyectado y vence a los 60 s."""

from datetime import datetime, timezone

from universal_bot.code_mode.clock import FakeClock
from universal_bot.code_mode.heartbeat import heartbeat_fresh, heartbeat_status, touch_heartbeat

T0 = datetime(2026, 10, 20, 18, 35, 1, tzinfo=timezone.utc)


def test_touch_is_fresh_until_twenty_seconds(tmp_path):
    clock = FakeClock(T0)
    touch_heartbeat(tmp_path, clock)
    assert (tmp_path / "runtime.heartbeat").read_text(encoding="utf-8") == T0.isoformat()
    assert heartbeat_fresh(tmp_path, clock) is True
    assert heartbeat_status(tmp_path, clock) == "ok"
    clock.advance(seconds=20)
    assert heartbeat_fresh(tmp_path, clock) is True
    clock.advance(seconds=1)
    assert heartbeat_fresh(tmp_path, clock) is False
    assert heartbeat_status(tmp_path, clock) == "ok"


def test_missing_or_older_than_sixty_is_unavailable(tmp_path):
    clock = FakeClock(T0)
    assert heartbeat_status(tmp_path, clock) == "no disponible"
    touch_heartbeat(tmp_path, clock)
    clock.advance(seconds=60)
    assert heartbeat_status(tmp_path, clock) == "ok"
    clock.advance(seconds=1)
    assert heartbeat_status(tmp_path, clock) == "no disponible"

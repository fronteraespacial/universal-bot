"""429 helper: backoff from retry_after, then give up."""

import pytest

from universal_bot.unified_progress.transport import RateLimited, retry_on_rate_limit


def test_retries_then_succeeds():
    sleeps: list[float] = []
    calls = {"n": 0}

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RateLimited(0.25)
        return "ok"

    assert retry_on_rate_limit(flaky, retries=3, sleep=sleeps.append) == "ok"
    assert calls["n"] == 3
    assert sleeps == [0.25, 0.25]


def test_exponential_backoff_without_retry_after():
    sleeps: list[float] = []

    def always() -> None:
        raise RateLimited(None)

    with pytest.raises(RateLimited):
        retry_on_rate_limit(always, retries=3, sleep=sleeps.append, base_s=0.4, cap_s=8.0)
    assert sleeps == [0.4, 0.8, 1.6]


def test_other_errors_are_not_retried():
    calls = {"n": 0}

    def boom() -> None:
        calls["n"] += 1
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError):
        retry_on_rate_limit(boom, retries=5, sleep=lambda _s: None)
    assert calls["n"] == 1

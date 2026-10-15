"""Discord IO boundary. Implementations live in the host; nothing here uses HTTP."""

from __future__ import annotations

import time
from typing import Any, Callable, Protocol


class RateLimited(Exception):
    """Transport hit HTTP 429. ``retry_after`` is seconds, when the API sent one."""

    def __init__(self, retry_after: float | None = None, message: str = "429") -> None:
        super().__init__(message)
        self.retry_after = retry_after


class MessageMissing(Exception):
    """Edit target is gone (HTTP 404 / unknown message). Callers recreate it."""


class DiscordTransport(Protocol):
    """Send, edit, and pin. The host supplies a real client; tests supply a fake."""

    def send(
        self,
        channel_id: str,
        *,
        content: str = "",
        embeds: list[dict[str, Any]] | None = None,
        reply_to: str | None = None,
        files: list[dict[str, Any]] | None = None,
    ) -> str:
        """Create a message and return its id."""
        ...

    def edit(
        self,
        channel_id: str,
        message_id: str,
        *,
        content: str | None = None,
        embeds: list[dict[str, Any]] | None = None,
    ) -> None:
        """Replace the message body. Raise ``MessageMissing`` when it is gone."""
        ...

    def pin(self, channel_id: str, message_id: str) -> None:
        """Pin ``message_id`` in ``channel_id``."""
        ...


def retry_on_rate_limit(
    fn: Callable[[], Any],
    *,
    retries: int,
    sleep: Callable[[float], None] | None = None,
    base_s: float = 0.4,
    cap_s: float = 8.0,
) -> Any:
    """Call ``fn`` and, on ``RateLimited``, wait and try again.

    ``retries`` is how many extra attempts follow the first 429. The delay is
    the server's ``retry_after`` when present, otherwise exponential backoff
    from ``base_s`` capped at ``cap_s``. Any other exception propagates.
    """
    pause = sleep or time.sleep
    attempt = 0
    while True:
        try:
            return fn()
        except RateLimited as exc:
            if attempt >= max(0, retries):
                raise
            if exc.retry_after is not None:
                delay = max(0.0, float(exc.retry_after))
            else:
                delay = min(cap_s, base_s * (2**attempt))
            pause(delay)
            attempt += 1

"""Shared fakes for unified-progress tests. No network."""

from __future__ import annotations

from typing import Any

from universal_bot.unified_progress.transport import MessageMissing, RateLimited


class FakeTransport:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.edits: list[dict[str, Any]] = []
        self.pins: list[dict[str, str]] = []
        self.missing: set[str] = set()
        self.fail_send_remaining = 0
        self.retry_after: float | None = 0.05
        self._seq = 0

    def send(
        self,
        channel_id: str,
        *,
        content: str = "",
        embeds: list[dict[str, Any]] | None = None,
        reply_to: str | None = None,
        files: list[dict[str, Any]] | None = None,
    ) -> str:
        if self.fail_send_remaining > 0:
            self.fail_send_remaining -= 1
            raise RateLimited(self.retry_after, "429")
        self._seq += 1
        message_id = f"m{self._seq}"
        self.sent.append(
            {
                "id": message_id,
                "channel_id": str(channel_id),
                "content": content,
                "embeds": embeds,
                "reply_to": reply_to,
                "files": files,
            }
        )
        return message_id

    def edit(
        self,
        channel_id: str,
        message_id: str,
        *,
        content: str | None = None,
        embeds: list[dict[str, Any]] | None = None,
    ) -> None:
        if message_id in self.missing:
            raise MessageMissing(f"404 unknown message {message_id}")
        self.edits.append(
            {
                "channel_id": str(channel_id),
                "message_id": str(message_id),
                "content": content,
                "embeds": embeds,
            }
        )

    def pin(self, channel_id: str, message_id: str) -> None:
        self.pins.append({"channel_id": str(channel_id), "message_id": str(message_id)})

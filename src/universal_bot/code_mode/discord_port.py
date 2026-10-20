"""Puerto de Discord. Los servicios no importan discord.py."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Button:
    custom_id: str
    label: str


@dataclass(frozen=True)
class Overwrite:
    target: str
    allow: tuple[str, ...]
    deny: tuple[str, ...] = ()


class DiscordPort(Protocol):
    def send(self, channel_id: int, content: str, *, thread_id: int | None = None) -> int: ...

    def send_buttons(
        self,
        channel_id: int,
        content: str,
        buttons: tuple[Button, ...],
        *,
        thread_id: int | None = None,
    ) -> int: ...

    def create_channel(
        self,
        guild_id: int,
        name: str,
        *,
        category_name: str,
        overwrites: tuple[Overwrite, ...],
    ) -> int: ...

    def create_thread(self, channel_id: int, name: str, *, wait: bool = False) -> int: ...

    def pin(self, channel_id: int, message_id: int, *, thread_id: int | None = None) -> None: ...

    def unpin(self, channel_id: int, message_id: int, *, thread_id: int | None = None) -> None: ...

    def reply_ephemeral(self, user_id: int, content: str) -> None: ...

    def check_permissions(self, guild_id: int, permission: str) -> bool: ...

    def channel_id_by_name(self, guild_id: int, name: str) -> int | None: ...

    def register_persistent_view(self, custom_id: str) -> None: ...

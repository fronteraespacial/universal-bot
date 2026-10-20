"""Discord en memoria para tests. No abre red."""

from __future__ import annotations

from dataclasses import dataclass, field

from universal_bot.code_mode.custom_id import parse_custom_id
from universal_bot.code_mode.discord_port import Button, Overwrite


@dataclass
class RecordedMessage:
    message_id: int
    channel_id: int
    thread_id: int | None
    content: str
    buttons: tuple[Button, ...]
    ephemeral: bool


@dataclass
class CreatedChannel:
    id: int
    guild_id: int
    name: str
    category_name: str
    overwrites: tuple[Overwrite, ...]


@dataclass
class CreatedThread:
    id: int
    channel_id: int
    name: str


@dataclass
class FakeDiscord:
    messages: list[RecordedMessage] = field(default_factory=list)
    channels: list[CreatedChannel] = field(default_factory=list)
    threads: list[CreatedThread] = field(default_factory=list)
    pins: list[tuple[int, int, int | None]] = field(default_factory=list)
    unpins: list[tuple[int, int, int | None]] = field(default_factory=list)
    ephemeral: list[tuple[int, str]] = field(default_factory=list)
    views: list[str] = field(default_factory=list)
    permissions: dict[str, bool] = field(default_factory=lambda: {"manage_channels": True})
    named_channels: dict[str, int] = field(
        default_factory=lambda: {"proyectos": 700, "admin-bot": 800}
    )
    _seq: int = 1
    create_channel_calls: int = 0

    def _next_id(self) -> int:
        value = self._seq
        self._seq += 1
        return value

    def send(self, channel_id: int, content: str, *, thread_id: int | None = None) -> int:
        message_id = self._next_id()
        self.messages.append(
            RecordedMessage(message_id, channel_id, thread_id, content, (), False)
        )
        return message_id

    def send_buttons(
        self,
        channel_id: int,
        content: str,
        buttons: tuple[Button, ...],
        *,
        thread_id: int | None = None,
    ) -> int:
        for button in buttons:
            parse_custom_id(button.custom_id)
        message_id = self._next_id()
        self.messages.append(
            RecordedMessage(message_id, channel_id, thread_id, content, tuple(buttons), False)
        )
        return message_id

    def create_channel(
        self,
        guild_id: int,
        name: str,
        *,
        category_name: str,
        overwrites: tuple[Overwrite, ...],
    ) -> int:
        self.create_channel_calls += 1
        channel_id = self._next_id()
        self.channels.append(CreatedChannel(channel_id, guild_id, name, category_name, overwrites))
        return channel_id

    def create_thread(self, channel_id: int, name: str) -> int:
        thread_id = self._next_id()
        self.threads.append(CreatedThread(thread_id, channel_id, name))
        return thread_id

    def pin(self, channel_id: int, message_id: int, *, thread_id: int | None = None) -> None:
        self.pins.append((channel_id, message_id, thread_id))

    def unpin(self, channel_id: int, message_id: int, *, thread_id: int | None = None) -> None:
        self.unpins.append((channel_id, message_id, thread_id))

    def reply_ephemeral(self, user_id: int, content: str) -> None:
        self.ephemeral.append((user_id, content))

    def check_permissions(self, guild_id: int, permission: str) -> bool:
        return bool(self.permissions.get(permission, False))

    def channel_id_by_name(self, guild_id: int, name: str) -> int | None:
        return self.named_channels.get(name)

    def register_persistent_view(self, custom_id: str) -> None:
        parse_custom_id(custom_id)
        self.views.append(custom_id)

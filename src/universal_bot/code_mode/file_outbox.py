"""Adaptador DiscordPort que escribe el spool del puente. No abre Discord."""

from __future__ import annotations

from pathlib import Path


class BridgeDomainError(RuntimeError):
    """El puente rechazó la operación con un error de dominio."""


class OutOfScope(BridgeDomainError):
    """El canal está fuera de #labcode, de los p- registrados o de sus hilos."""


class ToggleOff(BridgeDomainError):
    """El toggle del puente está apagado."""


class BridgeTimeout(TimeoutError):
    """El resultado de la operación no llegó dentro del plazo."""


class UnsupportedBridgeOp(RuntimeError):
    """Esa operación no existe en el puente."""


class FileOutboxDiscordPort:
    def __init__(
        self,
        spool: Path,
        *,
        clock,
        sleeper,
        timeout_s: float = 30.0,
        poll_interval_s: float = 0.25,
        admin_category_id: int | None = None,
        named_channels: dict[str, int] | None = None,
    ):
        self.spool = Path(spool)
        self.clock = clock
        self.sleeper = sleeper
        self.timeout_s = timeout_s
        self.poll_interval_s = poll_interval_s
        self.admin_category_id = admin_category_id
        self.named_channels = dict(named_channels or {})

    def send(self, channel_id: int, content: str, *, thread_id: int | None = None, reply_to: int | None = None, components=None, embeds=None) -> int:
        raise NotImplementedError("send")

    def send_buttons(self, channel_id: int, content: str, buttons, *, thread_id: int | None = None) -> int:
        raise NotImplementedError("send_buttons")

    def edit(self, channel_id: int, message_id: int, *, content=None, components=None, embeds=None) -> None:
        raise NotImplementedError("edit")

    def create_channel(self, guild_id: int, name: str, *, category_name: str, overwrites=(), topic: str | None = None, parent_id: int | None = None) -> int:
        raise NotImplementedError("create_channel")

    def create_thread(self, channel_id: int, name: str, *, from_message_id: int | None = None) -> int:
        raise NotImplementedError("create_thread")

    def pin(self, channel_id: int, message_id: int, *, thread_id: int | None = None) -> None:
        raise NotImplementedError("pin")

    def unpin(self, channel_id: int, message_id: int, *, thread_id: int | None = None) -> None:
        raise NotImplementedError("unpin")

    def reply_ephemeral(self, user_id: int, content: str) -> None:
        raise NotImplementedError("reply_ephemeral")

    def check_permissions(self, guild_id: int, permission: str) -> bool:
        raise NotImplementedError("check_permissions")

    def channel_id_by_name(self, guild_id: int, name: str) -> int | None:
        raise NotImplementedError("channel_id_by_name")

    def register_persistent_view(self, custom_id: str) -> None:
        raise NotImplementedError("register_persistent_view")

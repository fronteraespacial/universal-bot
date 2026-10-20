"""Adaptador DiscordPort que escribe el spool del puente. No abre Discord."""

from __future__ import annotations

from datetime import timedelta
import json
from pathlib import Path
import re

from universal_bot.code_mode.custom_id import parse_custom_id
from universal_bot.code_mode.discord_port import Button

_CHANNEL_NAME = re.compile(r"^p-[a-z0-9][a-z0-9-]{0,90}$")
_MENTIONS = {"parse": [], "replied_user": False}


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

    def send(
        self,
        channel_id: int,
        content: str,
        *,
        thread_id: int | None = None,
        reply_to: int | None = None,
        components=None,
        embeds=None,
    ) -> int:
        target = self._target(channel_id, thread_id)
        payload = self._emit(
            "send",
            channel_id=target,
            content=_content(content, embeds=embeds),
            reply_to=_optional_id(reply_to, "reply_to"),
            components=_checked_components(components),
            embeds=_embeds(embeds),
        )
        result = self._wait_result(payload["op_id"])
        return _result_id(result, "message_id")

    def send_buttons(self, channel_id: int, content: str, buttons, *, thread_id: int | None = None) -> int:
        return self.send(channel_id, content, thread_id=thread_id, components=_button_rows(buttons))

    def edit(self, channel_id: int, message_id: int, *, content=None, components=None, embeds=None) -> None:
        if content is None and components is None and embeds is None:
            raise ValueError("edit exige content, components o embeds")
        body = _content(content, embeds=embeds, allow_empty=True) if content is not None else None
        payload = self._emit(
            "edit",
            channel_id=_discord_id(channel_id, "channel_id"),
            message_id=_discord_id(message_id, "message_id"),
            content=body,
            components=_checked_components(components),
            embeds=_embeds(embeds),
        )
        self._wait_result(payload["op_id"])

    def create_channel(
        self,
        guild_id: int,
        name: str,
        *,
        category_name: str,
        overwrites=(),
        topic: str | None = None,
        parent_id: int | None = None,
    ) -> int:
        del guild_id, category_name, overwrites
        if not _CHANNEL_NAME.fullmatch(name or ""):
            raise ValueError(f"name inválido para create_channel: {name!r}")
        if topic is not None and len(topic) > 1024:
            raise ValueError("topic supera 1024 caracteres")
        payload = self._emit(
            "create_channel",
            name=name,
            topic=topic,
            parent_id=self._parent(parent_id),
        )
        result = self._wait_result(payload["op_id"])
        return _result_id(result, "channel_id")

    def create_thread(self, channel_id: int, name: str, *, from_message_id: int | None = None) -> int:
        if not isinstance(name, str) or not 1 <= len(name) <= 100:
            raise ValueError("name fuera de 1..100")
        payload = self._emit(
            "thread",
            channel_id=_discord_id(channel_id, "channel_id"),
            name=name,
            from_message_id=_optional_id(from_message_id, "from_message_id"),
        )
        result = self._wait_result(payload["op_id"])
        return _result_id(result, "thread_id")

    def pin(self, channel_id: int, message_id: int, *, thread_id: int | None = None) -> None:
        payload = self._emit(
            "pin",
            channel_id=self._target(channel_id, thread_id),
            message_id=_discord_id(message_id, "message_id"),
        )
        self._wait_result(payload["op_id"])

    def unpin(self, channel_id: int, message_id: int, *, thread_id: int | None = None) -> None:
        del channel_id, message_id, thread_id
        raise UnsupportedBridgeOp("unpin no existe en el puente")

    def reply_ephemeral(self, user_id: int, content: str) -> None:
        del user_id, content
        raise UnsupportedBridgeOp("reply_ephemeral no existe en el puente")

    def check_permissions(self, guild_id: int, permission: str) -> bool:
        del guild_id
        return permission == "manage_channels"

    def channel_id_by_name(self, guild_id: int, name: str) -> int | None:
        del guild_id
        return self.named_channels.get(name)

    def register_persistent_view(self, custom_id: str) -> None:
        parse_custom_id(custom_id)

    def _parent(self, parent_id: int | None) -> int | None:
        chosen = self.admin_category_id if parent_id is None else parent_id
        if chosen is None:
            return None
        if self.admin_category_id is None or chosen != self.admin_category_id:
            raise ValueError("parent_id solo puede ser la categoría ADMINISTRACIÓN")
        return _discord_id(chosen, "parent_id")

    def _target(self, channel_id: int, thread_id: int | None) -> int:
        _discord_id(channel_id, "channel_id")
        if thread_id is None:
            return channel_id
        return _discord_id(thread_id, "thread_id")

    def _emit(self, kind: str, **fields) -> dict:
        op_id = self._allocate(kind)
        payload = {
            "version": 1,
            "op_id": op_id,
            "op": kind,
            "allowed_mentions": dict(_MENTIONS),
        }
        for key, value in fields.items():
            if value is not None:
                payload[key] = value
        self._publish(op_id, payload)
        return payload

    def _allocate(self, kind: str) -> str:
        seq_path = self.spool / "op.seq"
        current = int(seq_path.read_text(encoding="utf-8")) if seq_path.is_file() else 0
        while True:
            current += 1
            stamp = self.clock.now().strftime("%Y%m%dT%H%M%S")
            op_id = f"{stamp}-{current:04d}-{kind}"
            if not self._taken(op_id):
                break
        seq_path.write_text(str(current), encoding="utf-8")
        return op_id

    def _taken(self, op_id: str) -> bool:
        outbox = self.spool / "outbox"
        names = (f"{op_id}.json", f"{op_id}.result.json")
        return any((outbox / name).exists() or (outbox / "done" / name).exists() for name in names)

    def _publish(self, op_id: str, payload: dict) -> None:
        outbox = self.spool / "outbox"
        outbox.mkdir(parents=True, exist_ok=True)
        tmp = outbox / f".{op_id}.tmp"
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(outbox / f"{op_id}.json")

    def _wait_result(self, op_id: str) -> dict:
        deadline = self.clock.now() + timedelta(seconds=self.timeout_s)
        limit = max(3, int(self.timeout_s / max(self.poll_interval_s, 0.001)) + 3)
        polls = 0
        while polls <= limit:
            found = self._read_result(op_id)
            if found is not None:
                return _accept(found)
            if self.clock.now() >= deadline:
                break
            polls += 1
            if polls > limit:
                break
            self.sleeper(self.poll_interval_s)
        raise BridgeTimeout(op_id)

    def _read_result(self, op_id: str) -> dict | None:
        path = self.spool / "outbox" / f"{op_id}.result.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))


def _discord_id(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} no es un id numérico")
    return value


def _optional_id(value: int | None, field: str) -> int | None:
    if value is None:
        return None
    return _discord_id(value, field)


def _content(content: str, *, embeds, allow_empty: bool = False) -> str:
    if not isinstance(content, str):
        raise ValueError("content no es texto")
    if len(content) > 2000:
        raise ValueError("content supera 2000 caracteres")
    if not content and not embeds and not allow_empty:
        raise ValueError("content vacío")
    return content


def _embeds(embeds) -> list | None:
    if embeds is None:
        return None
    rows = list(embeds)
    if len(rows) > 10:
        raise ValueError("embeds supera 10")
    return rows


def _button_rows(buttons) -> list:
    rows: list[dict] = []
    current: list[dict] = []
    for button in buttons:
        if not isinstance(button, Button):
            raise ValueError("botón inválido")
        parsed = parse_custom_id(button.custom_id)
        current.append(
            {
                "type": 2,
                "style": 2,
                "label": button.label,
                "custom_id": f"ublab:{parsed.kind}:{parsed.id}:{parsed.opt}",
            }
        )
        if len(current) == 5:
            rows.append({"type": 1, "components": current})
            current = []
    if current:
        rows.append({"type": 1, "components": current})
    return rows


def _checked_components(components) -> list | None:
    if components is None:
        return None
    _walk_ids(components)
    return list(components)


def _walk_ids(components) -> None:
    for item in components:
        if isinstance(item, Button):
            parse_custom_id(item.custom_id)
        elif isinstance(item, dict):
            if "custom_id" in item:
                parse_custom_id(item["custom_id"])
            nested = item.get("components")
            if nested:
                _walk_ids(nested)


def _accept(result: dict) -> dict:
    if result.get("ok"):
        return result
    error = str(result.get("error") or "")
    if error == "out_of_scope":
        raise OutOfScope("out_of_scope")
    if error == "toggle_off":
        raise ToggleOff("toggle_off")
    raise BridgeDomainError(error or "operación rechazada")


def _result_id(result: dict, key: str) -> int:
    value = result.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    raise BridgeDomainError(f"el resultado no trae {key}")

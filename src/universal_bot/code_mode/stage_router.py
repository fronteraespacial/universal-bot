"""Etapas del proyecto: hilo lazy, prefijo en modo hilo y texto simple."""

from __future__ import annotations

from dataclasses import dataclass, replace

from universal_bot.code_mode.discord_port import DiscordPort
from universal_bot.code_mode.models import Project, ProjectMode

_JARGON = frozenset({"diff", "pr", "prs", "stack", "commit", "merge", "pytest"})
_O2_HEADER = "O2 · correctiva"


class StageOrderError(Exception):
    pass


@dataclass(frozen=True)
class StageView:
    key: str
    thread_id: int | None
    header: str | None
    created_thread: bool


class StageRouter:
    def __init__(self, discord: DiscordPort, db_path=None):
        if db_path is not None:
            raise NotImplementedError
        self.discord = discord
        self.db_path = None
        self._stages: dict[tuple[str, str], StageView] = {}

    def enter(self, project: Project, stage_key: str, *, wave: str | None = None) -> StageView:
        if stage_key == "03-plan" and (project.id, "02-lab") not in self._stages:
            raise StageOrderError("02-lab antes de 03-plan")
        wave_name = wave or project.wave
        header = _O2_HEADER if wave_name == "O2" and _reuses_thread(stage_key) else None
        existing = self._stages.get((project.id, stage_key))
        if existing is not None:
            return replace(existing, header=header, created_thread=False)
        created = False
        thread_id: int | None
        if project.mode == ProjectMode.CHANNEL:
            thread_id = self.discord.create_thread(project.channel_id, stage_key)
            created = True
        else:
            thread_id = project.root_thread_id
        view = StageView(stage_key, thread_id, header, created)
        self._stages[(project.id, stage_key)] = view
        return view

    def post(self, project: Project, stage_key: str, technical: str, *, wave: str | None = None) -> StageView:
        view = self.enter(project, stage_key, wave=wave)
        plain = render_plain(technical)
        if project.mode == ProjectMode.THREAD or view.thread_id is None:
            technical_text = f"[{stage_key}] {technical}"
            if view.header:
                technical_text = f"{view.header}\n{technical_text}"
            destination = view.thread_id
            self.discord.send(project.channel_id, technical_text, thread_id=destination)
            self.discord.send(project.channel_id, plain, thread_id=destination)
            return view
        technical_text = technical if view.header is None else f"{view.header}\n{technical}"
        self.discord.send(project.channel_id, technical_text, thread_id=view.thread_id)
        self.discord.send(project.channel_id, plain, thread_id=None)
        return view


def render_plain(text: str) -> str:
    kept: list[str] = []
    for raw in text.split():
        token = raw.strip(".,:;()[]¡!¿?\"'`").lower()
        if token in _JARGON:
            continue
        kept.append(raw)
    return " ".join(kept)


def render_technical(text: str) -> str:
    return text


def _reuses_thread(stage_key: str) -> bool:
    return stage_key.startswith("04-impl") or stage_key == "05-verificacion"

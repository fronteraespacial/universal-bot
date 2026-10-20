"""Etapas del proyecto: hilo lazy, prefijo en modo hilo y texto simple."""

from __future__ import annotations

from universal_bot.code_mode.discord_port import DiscordPort
from universal_bot.code_mode.models import Project


class StageOrderError(Exception):
    pass


class StageRouter:
    def __init__(self, discord: DiscordPort):
        self.discord = discord

    def enter(self, project: Project, stage_key: str, *, wave: str | None = None):
        raise NotImplementedError("enter")

    def post(self, project: Project, stage_key: str, technical: str, *, wave: str | None = None):
        raise NotImplementedError("post")


def render_plain(text: str) -> str:
    raise NotImplementedError("render_plain")


def render_technical(text: str) -> str:
    raise NotImplementedError("render_technical")

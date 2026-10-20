"""Pregunta pendiente, botones y reanudación del job."""

from __future__ import annotations

from universal_bot.code_mode.clock import Clock
from universal_bot.code_mode.config import CodeModeConfig
from universal_bot.code_mode.discord_port import DiscordPort
from universal_bot.code_mode.projects import ProjectLedger
from universal_bot.store import JobStore


class AskBridge:
    def __init__(
        self,
        db_path,
        job_store: JobStore,
        discord: DiscordPort,
        clock: Clock,
        projects: ProjectLedger,
        config: CodeModeConfig,
    ):
        self.db_path = db_path
        self.job_store = job_store
        self.discord = discord
        self.clock = clock
        self.projects = projects
        self.config = config

    def ask(self, **kwargs):
        raise NotImplementedError("ask")

    def answer(self, question_id: str, option: str, user_id: int):
        raise NotImplementedError("answer")

    def get(self, question_id: str):
        raise NotImplementedError("get")

    def tick(self):
        raise NotImplementedError("tick")

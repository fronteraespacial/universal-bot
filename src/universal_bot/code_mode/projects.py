"""Proyectos ligados a una sesión. El checkpoint vive acá."""

from __future__ import annotations

from pathlib import Path

from universal_bot.code_mode.clock import Clock
from universal_bot.code_mode.models import Project, ProjectCheckpoint, ProjectState


class ProjectLedger:
    def __init__(self, db_path: Path | str, clock: Clock):
        raise NotImplementedError("ProjectLedger")

    def create_project(self, **fields: object) -> Project:
        raise NotImplementedError("create_project")

    def get_project(self, project_id: str) -> Project | None:
        raise NotImplementedError("get_project")

    def save_project(self, project: Project) -> None:
        raise NotImplementedError("save_project")

    def begin_commit(self, project_id: str) -> None:
        raise NotImplementedError("begin_commit")

    def finish_commit(self, project_id: str) -> ProjectCheckpoint | None:
        raise NotImplementedError("finish_commit")

    def request_checkpoint(self, project_id: str) -> tuple[ProjectState | None, str | None, bool]:
        raise NotImplementedError("request_checkpoint")

    def last_checkpoint(self, project_id: str) -> ProjectCheckpoint | None:
        raise NotImplementedError("last_checkpoint")

    def count_open_channel_projects(self, guild_id: int) -> int:
        raise NotImplementedError("count_open_channel_projects")

    def slugs(self, guild_id: int) -> tuple[str, ...]:
        raise NotImplementedError("slugs")

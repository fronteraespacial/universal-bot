"""Proyectos ligados a una sesión. El checkpoint vive acá."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import json
import uuid

from universal_bot.code_mode.clock import Clock
from universal_bot.code_mode.db import connect, dump_dt, load_dt
from universal_bot.code_mode.models import (
    Project,
    ProjectCheckpoint,
    ProjectMode,
    ProjectState,
    SecurityCheckResult,
)

_CLOSED = (
    ProjectState.DONE.value,
    ProjectState.ARCHIVED.value,
    ProjectState.DECLINED.value,
    ProjectState.CANCELLED.value,
)
_PAUSABLE = {ProjectState.RUNNING, ProjectState.LAB_RUNNING}


@dataclass(frozen=True)
class CheckpointRequest:
    state: ProjectState | None
    resume_token: str | None
    deferred: bool


class ProjectLedger:
    def __init__(self, db_path: Path | str, clock: Clock):
        self.db_path = Path(db_path)
        self.clock = clock
        self._init_db()

    def _init_db(self) -> None:
        with connect(self.db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS code_projects (
                    id TEXT PRIMARY KEY,
                    guild_id INTEGER NOT NULL,
                    requester_id INTEGER NOT NULL,
                    origin_message_id INTEGER NOT NULL,
                    slug TEXT NOT NULL,
                    title_plain TEXT NOT NULL,
                    tier TEXT NOT NULL,
                    work_type TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    state TEXT NOT NULL,
                    channel_id INTEGER,
                    root_thread_id INTEGER,
                    run_id TEXT NOT NULL,
                    wave TEXT NOT NULL,
                    sandbox_id TEXT,
                    last_security_check TEXT,
                    requires_production INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS project_runtime (
                    project_id TEXT PRIMARY KEY,
                    in_commit INTEGER NOT NULL DEFAULT 0,
                    checkpoint_deferred INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (project_id) REFERENCES code_projects(id)
                );

                CREATE TABLE IF NOT EXISTS project_checkpoints (
                    project_id TEXT PRIMARY KEY,
                    resume_token TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (project_id) REFERENCES code_projects(id)
                );
                """
            )

    def create_project(self, **fields: object) -> Project:
        now = self.clock.now()
        project = Project(
            id=str(fields.get("id") or f"P-{uuid.uuid4().hex[:12]}"),
            guild_id=int(fields["guild_id"]),
            requester_id=int(fields["requester_id"]),
            origin_message_id=int(fields.get("origin_message_id", 0)),
            slug=str(fields.get("slug", "proyecto")),
            title_plain=str(fields.get("title_plain", "Proyecto")),
            tier=str(fields.get("tier", "T2")),
            work_type=str(fields.get("work_type", "evolving-product")),
            mode=ProjectMode(fields.get("mode", ProjectMode.THREAD)),
            state=ProjectState(fields.get("state", ProjectState.RUNNING)),
            channel_id=_optional_int(fields.get("channel_id")),
            root_thread_id=_optional_int(fields.get("root_thread_id")),
            run_id=str(fields.get("run_id", "R-local")),
            wave=str(fields.get("wave", "O1")),
            sandbox_id=_optional_str(fields.get("sandbox_id")),
            last_security_check=fields.get("last_security_check"),  # type: ignore[arg-type]
            requires_production=bool(fields.get("requires_production", False)),
            created_at=fields.get("created_at", now),  # type: ignore[arg-type]
            updated_at=fields.get("updated_at", now),  # type: ignore[arg-type]
        )
        self.save_project(project)
        return project

    def save_project(self, project: Project) -> None:
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO code_projects (
                    id, guild_id, requester_id, origin_message_id, slug, title_plain,
                    tier, work_type, mode, state, channel_id, root_thread_id, run_id,
                    wave, sandbox_id, last_security_check, requires_production,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    guild_id = excluded.guild_id,
                    requester_id = excluded.requester_id,
                    origin_message_id = excluded.origin_message_id,
                    slug = excluded.slug,
                    title_plain = excluded.title_plain,
                    tier = excluded.tier,
                    work_type = excluded.work_type,
                    mode = excluded.mode,
                    state = excluded.state,
                    channel_id = excluded.channel_id,
                    root_thread_id = excluded.root_thread_id,
                    run_id = excluded.run_id,
                    wave = excluded.wave,
                    sandbox_id = excluded.sandbox_id,
                    last_security_check = excluded.last_security_check,
                    requires_production = excluded.requires_production,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at
                """,
                _project_row(project),
            )

    def get_project(self, project_id: str) -> Project | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM code_projects WHERE id = ?",
                (project_id,),
            ).fetchone()
        if row is None:
            return None
        return _project_from_row(row)

    def begin_commit(self, project_id: str) -> None:
        self._ensure_runtime(project_id)
        self._set_flag(project_id, "in_commit", True)

    def finish_commit(self, project_id: str) -> ProjectCheckpoint | None:
        deferred = self._flag(project_id, "checkpoint_deferred")
        self._set_flag(project_id, "in_commit", False)
        self._set_flag(project_id, "checkpoint_deferred", False)
        if not deferred:
            return None
        project = self.get_project(project_id)
        if project is None or project.state not in _PAUSABLE:
            return None
        return self._pause(project)

    def request_checkpoint(self, project_id: str) -> CheckpointRequest:
        project = self.get_project(project_id)
        if project is None:
            return CheckpointRequest(None, None, False)
        if project.state not in _PAUSABLE:
            return CheckpointRequest(project.state, None, False)
        if self._flag(project_id, "in_commit"):
            self._ensure_runtime(project_id)
            self._set_flag(project_id, "checkpoint_deferred", True)
            return CheckpointRequest(project.state, None, True)
        checkpoint = self._pause(project)
        return CheckpointRequest(ProjectState.PAUSED, checkpoint.resume_token, False)

    def last_checkpoint(self, project_id: str) -> ProjectCheckpoint | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM project_checkpoints WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        if row is None:
            return None
        return ProjectCheckpoint(row["project_id"], row["resume_token"], load_dt(row["created_at"]))

    def count_open_channel_projects(self, guild_id: int) -> int:
        marks = ",".join("?" for _ in _CLOSED)
        with connect(self.db_path) as conn:
            row = conn.execute(
                f"""
                SELECT COUNT(*) AS cnt FROM code_projects
                WHERE guild_id = ? AND mode = ? AND state NOT IN ({marks})
                """,
                (guild_id, ProjectMode.CHANNEL.value, *_CLOSED),
            ).fetchone()
        return int(row["cnt"])

    def slugs(self, guild_id: int) -> tuple[str, ...]:
        with connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT slug FROM code_projects WHERE guild_id = ? ORDER BY created_at, id",
                (guild_id,),
            ).fetchall()
        return tuple(row["slug"] for row in rows)

    def _pause(self, project: Project) -> ProjectCheckpoint:
        now = self.clock.now()
        token = f"resume-{uuid.uuid4().hex[:12]}"
        self.save_project(replace(project, state=ProjectState.PAUSED, updated_at=now))
        checkpoint = ProjectCheckpoint(project.id, token, now)
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO project_checkpoints (project_id, resume_token, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    resume_token = excluded.resume_token,
                    created_at = excluded.created_at
                """,
                (checkpoint.project_id, checkpoint.resume_token, dump_dt(checkpoint.created_at)),
            )
        return checkpoint

    def _ensure_runtime(self, project_id: str) -> None:
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO project_runtime (project_id, in_commit, checkpoint_deferred)
                VALUES (?, 0, 0)
                """,
                (project_id,),
            )

    def _flag(self, project_id: str, column: str) -> bool:
        if column not in {"in_commit", "checkpoint_deferred"}:
            raise ValueError(column)
        with connect(self.db_path) as conn:
            row = conn.execute(
                f"SELECT {column} AS flag FROM project_runtime WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        return bool(row and row["flag"])

    def _set_flag(self, project_id: str, column: str, value: bool) -> None:
        if column not in {"in_commit", "checkpoint_deferred"}:
            raise ValueError(column)
        self._ensure_runtime(project_id)
        with connect(self.db_path) as conn:
            conn.execute(
                f"UPDATE project_runtime SET {column} = ? WHERE project_id = ?",
                (1 if value else 0, project_id),
            )


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _dump_security(result: SecurityCheckResult | None) -> str | None:
    if result is None:
        return None
    return json.dumps(
        {
            "project_id": result.project_id,
            "sandbox_id": result.sandbox_id,
            "checked_at": result.checked_at.isoformat(),
            "passed": result.passed,
            "encapsulable": result.encapsulable,
            "violations": list(result.violations),
            "detail_ref": result.detail_ref,
        }
    )


def _load_security(raw: str | None) -> SecurityCheckResult | None:
    if not raw:
        return None
    payload = json.loads(raw)
    return SecurityCheckResult(
        project_id=payload["project_id"],
        sandbox_id=payload["sandbox_id"],
        checked_at=load_dt(payload["checked_at"]),
        passed=bool(payload["passed"]),
        encapsulable=bool(payload["encapsulable"]),
        violations=tuple(payload["violations"]),
        detail_ref=payload["detail_ref"],
    )


def _project_row(project: Project) -> tuple:
    return (
        project.id,
        project.guild_id,
        project.requester_id,
        project.origin_message_id,
        project.slug,
        project.title_plain,
        project.tier,
        project.work_type,
        project.mode.value,
        project.state.value,
        project.channel_id,
        project.root_thread_id,
        project.run_id,
        project.wave,
        project.sandbox_id,
        _dump_security(project.last_security_check),
        1 if project.requires_production else 0,
        dump_dt(project.created_at),
        dump_dt(project.updated_at),
    )


def _project_from_row(row: object) -> Project:
    return Project(
        id=row["id"],
        guild_id=row["guild_id"],
        requester_id=row["requester_id"],
        origin_message_id=row["origin_message_id"],
        slug=row["slug"],
        title_plain=row["title_plain"],
        tier=row["tier"],
        work_type=row["work_type"],
        mode=ProjectMode(row["mode"]),
        state=ProjectState(row["state"]),
        channel_id=row["channel_id"],
        root_thread_id=row["root_thread_id"],
        run_id=row["run_id"],
        wave=row["wave"],
        sandbox_id=row["sandbox_id"],
        last_security_check=_load_security(row["last_security_check"]),
        requires_production=bool(row["requires_production"]),
        created_at=load_dt(row["created_at"]),
        updated_at=load_dt(row["updated_at"]),
    )

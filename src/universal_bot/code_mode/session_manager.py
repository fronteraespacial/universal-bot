"""Sesión pegajosa de modo código por ubicación."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import uuid

from universal_bot.code_mode.clock import Clock
from universal_bot.code_mode.config import CodeModeConfig, parse_duration, role_allowed
from universal_bot.code_mode.db import connect, dump_dt, load_dt
from universal_bot.code_mode.discord_port import Button, DiscordPort
from universal_bot.code_mode.models import ActivationKind, CodeModeSession, Location, SessionStatus
from universal_bot.code_mode.projects import ProjectLedger
from universal_bot.code_mode.text_rules import (
    duration_from_text,
    is_command,
    is_manual_trigger,
    is_trivial_message,
)

PIN_TEXT = "Modo programación activo."
EXIT_LABEL = "Salir de modo programación"
WARN_TEXT = "El modo programación está por vencer."
EXIT_FORBIDDEN = "No podés salir de este modo."
ACTIVATE_FORBIDDEN = "No tenés permiso para activar el modo código."
EXIT_OK = "Salimos de modo programación. El trabajo quedó guardado; reactivá para seguir."
EXPIRE_OK = "Se venció el modo programación. El trabajo quedó guardado; reactivá para seguir."


@dataclass(frozen=True)
class ActivateResult:
    ok: bool
    reason: str
    session: CodeModeSession | None


@dataclass(frozen=True)
class ExitResult:
    ok: bool
    reason: str
    session: CodeModeSession | None
    resume_token: str | None = None


@dataclass(frozen=True)
class RouteDecision:
    kind: str
    session: CodeModeSession | None


class SessionManager:
    def __init__(
        self,
        db_path: Path | str,
        clock: Clock,
        discord: DiscordPort,
        config: CodeModeConfig,
        projects: ProjectLedger,
    ):
        self.db_path = Path(db_path)
        self.clock = clock
        self.discord = discord
        self.config = config
        self.projects = projects
        self._init_db()
        self._recover()

    def activate(
        self,
        location: Location,
        actor_id: int,
        actor_roles: tuple[str, ...],
        duration: str,
        activation: str,
        project_id: str | None = None,
        bypass_role_check: bool = False,
    ) -> ActivateResult:
        if not bypass_role_check and not role_allowed(self.config.roles.can_activate, actor_roles):
            self.discord.reply_ephemeral(actor_id, ACTIVATE_FORBIDDEN)
            return ActivateResult(False, "forbidden", None)
        now = self.clock.now()
        until, warn_at = self._window(now, duration)
        existing = self._exact_active(location)
        if existing is not None:
            self._update_window(existing.id, until, warn_at)
            return ActivateResult(True, "extended", self.get(existing.id))
        session_id = f"CMS-{uuid.uuid4().hex[:12]}"
        message_id = self.discord.send_buttons(
            location.channel_id,
            PIN_TEXT,
            (Button(f"ublab:exit:{session_id}", EXIT_LABEL),),
            thread_id=location.thread_id,
        )
        self.discord.pin(location.channel_id, message_id, thread_id=location.thread_id)
        session = CodeModeSession(
            id=session_id,
            guild_id=location.guild_id,
            channel_id=location.channel_id,
            thread_id=location.thread_id,
            activated_by=actor_id,
            activation=activation,
            since=now,
            until=until,
            warn_at=warn_at,
            project_id=project_id,
            pinned_message_id=message_id,
            status=SessionStatus.ACTIVE,
            ended_by=None,
            ended_at=None,
        )
        self._insert(session)
        return ActivateResult(True, "activated", session)

    def handle_text(
        self,
        location: Location,
        actor_id: int,
        actor_roles: tuple[str, ...],
        text: str,
    ) -> ActivateResult:
        if not is_manual_trigger(text, self.config):
            decision = self.route(location, text)
            return ActivateResult(False, decision.kind, decision.session)
        activation = ActivationKind.COMMAND if is_command(text, self.config) else ActivationKind.MANUAL_PHRASE
        return self.activate(
            location,
            actor_id,
            actor_roles,
            duration_from_text(text, self.config),
            activation.value,
        )

    def resolve(self, location: Location) -> CodeModeSession | None:
        own = self._exact_active(location)
        if own is not None:
            return own
        if location.thread_id is None:
            return None
        return self._exact_active(Location(location.guild_id, location.channel_id, None))

    def get(self, session_id: str) -> CodeModeSession | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM code_mode_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return _session_from_row(row)

    def exit(
        self,
        location: Location,
        actor_id: int,
        actor_roles: tuple[str, ...],
    ) -> ExitResult:
        session = self._exact_active(location)
        if session is None:
            return ExitResult(False, "no_session", None, None)
        if not role_allowed(
            self.config.who_can_exit,
            actor_roles,
            actor_id=actor_id,
            activator_id=session.activated_by,
        ):
            self.discord.reply_ephemeral(actor_id, EXIT_FORBIDDEN)
            return ExitResult(False, "forbidden", session, None)
        return self._end(session, actor_id, "exit")

    def finish_atomic_step(self, project_id: str) -> ExitResult | None:
        checkpoint = self.projects.finish_commit(project_id)
        pending = self._pending_for_project(project_id)
        if checkpoint is None or pending is None:
            return None
        session_id, kind = pending
        session = self.get(session_id)
        if session is None:
            return None
        self._mark_ended(session, session.activated_by, _status_for(kind))
        self._announce_end(session, kind)
        return ExitResult(True, _reason_for(kind), self.get(session_id), checkpoint.resume_token)

    def tick(self) -> tuple[str, ...]:
        events: list[str] = []
        now = self.clock.now()
        for session in self._list_active():
            if session.until is not None and now >= session.until:
                self._end(session, None, "expire")
                events.append("expired")
                continue
            if self._due_warning(session, now):
                self._warn(session)
                events.append("warned")
        return tuple(events)

    def route(self, location: Location, text: str) -> RouteDecision:
        session = self.resolve(location)
        if session is None:
            return RouteDecision("outside", None)
        if self.config.trivial_to_basic_cli and is_trivial_message(text):
            return RouteDecision("basic_cli", session)
        return RouteDecision("code_cli", session)

    def _window(self, now, duration: str):
        delta = parse_duration(duration)
        if delta is None:
            return None, None
        until = now + delta
        warn_delta = parse_duration(self.config.warn_before)
        warn_at = None if warn_delta is None else until - warn_delta
        return until, warn_at

    def _end(self, session: CodeModeSession, actor_id: int | None, kind: str) -> ExitResult:
        token = None
        if session.project_id:
            outcome = self.projects.request_checkpoint(session.project_id)
            if outcome.deferred:
                self._set_pending(session.id, kind)
                return ExitResult(False, "deferred", self.get(session.id), None)
            token = outcome.resume_token
        self._mark_ended(session, actor_id, _status_for(kind))
        self._announce_end(session, kind)
        return ExitResult(True, _reason_for(kind), self.get(session.id), token)

    def _warn(self, session: CodeModeSession) -> None:
        self.discord.send_buttons(
            session.channel_id,
            WARN_TEXT,
            (
                Button(f"ublab:extend:{session.id}", "Extender"),
                Button(f"ublab:exit:{session.id}", "Salir ahora"),
            ),
            thread_id=session.thread_id,
        )
        with connect(self.db_path) as conn:
            conn.execute(
                "UPDATE code_mode_sessions SET warned = 1 WHERE id = ?",
                (session.id,),
            )

    def _announce_end(self, session: CodeModeSession, kind: str) -> None:
        if session.pinned_message_id is not None:
            self.discord.unpin(
                session.channel_id,
                session.pinned_message_id,
                thread_id=session.thread_id,
            )
        text = EXIT_OK if kind == "exit" else EXPIRE_OK
        self.discord.send(session.channel_id, text, thread_id=session.thread_id)

    def _due_warning(self, session: CodeModeSession, now) -> bool:
        if session.warn_at is None or now < session.warn_at:
            return False
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT warned FROM code_mode_sessions WHERE id = ?",
                (session.id,),
            ).fetchone()
        return bool(row) and not row["warned"]

    def _recover(self) -> None:
        now = self.clock.now()
        for session in self._list_active():
            if session.until is not None and session.until <= now:
                self._end(session, None, "expire")
                continue
            if session.pinned_message_id is not None:
                self.discord.register_persistent_view(f"ublab:exit:{session.id}")

    def _exact_active(self, location: Location) -> CodeModeSession | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT * FROM code_mode_sessions
                WHERE guild_id = ? AND channel_id = ? AND thread_key = ? AND status = ?
                """,
                (location.guild_id, location.channel_id, _thread_key(location.thread_id), SessionStatus.ACTIVE.value),
            ).fetchone()
        if row is None:
            return None
        return _session_from_row(row)

    def _list_active(self) -> tuple[CodeModeSession, ...]:
        with connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM code_mode_sessions WHERE status = ? ORDER BY since, id",
                (SessionStatus.ACTIVE.value,),
            ).fetchall()
        return tuple(_session_from_row(row) for row in rows)

    def _insert(self, session: CodeModeSession) -> None:
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO code_mode_sessions (
                    id, guild_id, channel_id, thread_id, thread_key, activated_by, activation,
                    since, until, warn_at, project_id, pinned_message_id, status, ended_by,
                    ended_at, warned, pending_end
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL)
                """,
                _session_values(session),
            )

    def _update_window(self, session_id: str, until, warn_at) -> None:
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE code_mode_sessions
                SET until = ?, warn_at = ?, warned = 0, pending_end = NULL
                WHERE id = ?
                """,
                (dump_dt(until), dump_dt(warn_at), session_id),
            )

    def _set_pending(self, session_id: str, kind: str) -> None:
        with connect(self.db_path) as conn:
            conn.execute(
                "UPDATE code_mode_sessions SET pending_end = ? WHERE id = ?",
                (kind, session_id),
            )

    def _pending_for_project(self, project_id: str) -> tuple[str, str] | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT id, pending_end FROM code_mode_sessions
                WHERE project_id = ? AND pending_end IS NOT NULL AND status = ?
                """,
                (project_id, SessionStatus.ACTIVE.value),
            ).fetchone()
        if row is None:
            return None
        return row["id"], row["pending_end"]

    def _mark_ended(self, session: CodeModeSession, actor_id: int | None, status: SessionStatus) -> None:
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE code_mode_sessions
                SET status = ?, ended_by = ?, ended_at = ?, pending_end = NULL
                WHERE id = ?
                """,
                (status.value, actor_id, dump_dt(self.clock.now()), session.id),
            )

    def _init_db(self) -> None:
        with connect(self.db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS code_mode_sessions (
                    id TEXT PRIMARY KEY,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    thread_id INTEGER,
                    thread_key TEXT NOT NULL,
                    activated_by INTEGER NOT NULL,
                    activation TEXT NOT NULL,
                    since TEXT NOT NULL,
                    until TEXT,
                    warn_at TEXT,
                    project_id TEXT,
                    pinned_message_id INTEGER,
                    status TEXT NOT NULL,
                    ended_by INTEGER,
                    ended_at TEXT,
                    warned INTEGER NOT NULL DEFAULT 0,
                    pending_end TEXT
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_session
                ON code_mode_sessions(guild_id, channel_id, thread_key)
                WHERE status = 'ACTIVE';
                """
            )


def _thread_key(thread_id: int | None) -> str:
    if thread_id is None:
        return ""
    return str(thread_id)


def _status_for(kind: str) -> SessionStatus:
    if kind == "expire":
        return SessionStatus.EXPIRED
    return SessionStatus.EXITED


def _reason_for(kind: str) -> str:
    if kind == "expire":
        return "expired"
    return "exited"


def _session_values(session: CodeModeSession) -> tuple:
    return (
        session.id,
        session.guild_id,
        session.channel_id,
        session.thread_id,
        _thread_key(session.thread_id),
        session.activated_by,
        session.activation,
        dump_dt(session.since),
        dump_dt(session.until),
        dump_dt(session.warn_at),
        session.project_id,
        session.pinned_message_id,
        session.status.value if isinstance(session.status, SessionStatus) else session.status,
        session.ended_by,
        dump_dt(session.ended_at),
    )


def _session_from_row(row: object) -> CodeModeSession:
    return CodeModeSession(
        id=row["id"],
        guild_id=row["guild_id"],
        channel_id=row["channel_id"],
        thread_id=row["thread_id"],
        activated_by=row["activated_by"],
        activation=row["activation"],
        since=load_dt(row["since"]),
        until=load_dt(row["until"]),
        warn_at=load_dt(row["warn_at"]),
        project_id=row["project_id"],
        pinned_message_id=row["pinned_message_id"],
        status=row["status"],
        ended_by=row["ended_by"],
        ended_at=load_dt(row["ended_at"]),
    )

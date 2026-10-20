"""Etapas del proyecto: hilo lazy, prefijo en modo hilo y texto simple."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path

from universal_bot.code_mode.db import connect
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
        self.discord = discord
        self.db_path = None if db_path is None else Path(db_path)
        self._stages: dict[tuple[str, str], StageView] = {}
        if self.db_path is not None:
            self._init_db()
            self._load()

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
        self._save(project.id, view)
        return view

    def post(self, project: Project, stage_key: str, technical: str, *, wave: str | None = None) -> StageView:
        view = self.enter(project, stage_key, wave=wave)
        plain = render_plain(technical)
        if project.mode == ProjectMode.CHANNEL and view.thread_id is None:
            self._remember_pending(project, stage_key, technical)
            return view
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
        return view

    def flush_pending(self) -> None:
        spool = getattr(self.discord, "spool", None)
        if spool is None:
            return
        for row in self._pending_rows():
            result = _result_file(Path(spool), row["op_id"])
            if result is None or result.get("ok") is not True:
                continue
            thread_id = _bridge_id(result.get("thread_id"))
            if thread_id is None:
                continue
            self.discord.send(row["channel_id"], row["technical"], thread_id=thread_id)
            self._stages[(row["project_id"], row["stage_key"])] = StageView(
                row["stage_key"],
                thread_id,
                None,
                False,
            )
            self._save(row["project_id"], self._stages[(row["project_id"], row["stage_key"])])
            self._drop_pending(row["project_id"], row["stage_key"])

    def _init_db(self) -> None:
        with connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS stage_threads (
                    project_id TEXT NOT NULL,
                    stage_key TEXT NOT NULL,
                    thread_id INTEGER,
                    PRIMARY KEY (project_id, stage_key)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_stage_posts (
                    project_id TEXT NOT NULL,
                    stage_key TEXT NOT NULL,
                    channel_id INTEGER NOT NULL,
                    op_id TEXT,
                    technical TEXT NOT NULL,
                    PRIMARY KEY (project_id, stage_key)
                )
                """
            )

    def _load(self) -> None:
        with connect(self.db_path) as conn:
            rows = conn.execute("SELECT project_id, stage_key, thread_id FROM stage_threads").fetchall()
        for row in rows:
            self._stages[(row["project_id"], row["stage_key"])] = StageView(
                row["stage_key"],
                row["thread_id"],
                None,
                False,
            )

    def _save(self, project_id: str, view: StageView) -> None:
        if self.db_path is None:
            return
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO stage_threads (project_id, stage_key, thread_id)
                VALUES (?, ?, ?)
                ON CONFLICT(project_id, stage_key) DO UPDATE SET thread_id = excluded.thread_id
                """,
                (project_id, view.key, view.thread_id),
            )

    def _remember_pending(self, project: Project, stage_key: str, technical: str) -> None:
        if self.db_path is None or project.channel_id is None:
            return
        ops = getattr(self.discord, "op_ids", None)
        op_id = ops[-1] if ops else None
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO pending_stage_posts (project_id, stage_key, channel_id, op_id, technical)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(project_id, stage_key) DO UPDATE SET
                    channel_id = excluded.channel_id,
                    op_id = excluded.op_id,
                    technical = excluded.technical
                """,
                (project.id, stage_key, project.channel_id, op_id, technical),
            )

    def _pending_rows(self) -> list:
        if self.db_path is None:
            return []
        with connect(self.db_path) as conn:
            return list(conn.execute("SELECT project_id, stage_key, channel_id, op_id, technical FROM pending_stage_posts"))

    def _drop_pending(self, project_id: str, stage_key: str) -> None:
        if self.db_path is None:
            return
        with connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM pending_stage_posts WHERE project_id = ? AND stage_key = ?",
                (project_id, stage_key),
            )


def _result_file(spool: Path, op_id: str | None) -> dict | None:
    if not op_id:
        return None
    path = spool / "outbox" / f"{op_id}.result.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _bridge_id(value) -> int | None:
    """El puente escribe los ids como strings de dígitos; también se aceptan ints."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


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

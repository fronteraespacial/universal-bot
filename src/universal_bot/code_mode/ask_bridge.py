"""Pregunta pendiente, botones y reanudación del job."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import uuid

from universal_bot.code_mode.clock import Clock
from universal_bot.code_mode.config import CodeModeConfig, parse_duration
from universal_bot.code_mode.custom_id import build_custom_id
from universal_bot.code_mode.db import connect, dump_dt, load_dt
from universal_bot.code_mode.discord_port import Button, DiscordPort
from universal_bot.code_mode.models import BLOCKING_QUESTION_KINDS, PendingQuestion, ProjectState, QuestionKind
from universal_bot.code_mode.projects import ProjectLedger
from universal_bot.contracts import JobRequest, JobStatus
from universal_bot.store import JobStore

FORBIDDEN = "No podés aprobar esto."


@dataclass(frozen=True)
class AnswerResult:
    accepted: bool
    duplicate: bool
    answer: str | None
    resume_job_id: str | None


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
        self.db_path = Path(db_path)
        self.job_store = job_store
        self.discord = discord
        self.clock = clock
        self.projects = projects
        self.config = config
        self._init_db()

    def ask(
        self,
        *,
        project_id: str,
        stage_key: str,
        kind: str,
        prompt_plain: str,
        options: tuple[str, ...],
        allowed_approvers: tuple[int, ...],
        job_id: str | None,
        resume_token: str,
        channel_id: int,
        thread_id: int | None,
        blocking: bool | None = None,
    ) -> PendingQuestion:
        if kind == "plan_approval":
            raise ValueError("plan_approval no existe")
        question_kind = QuestionKind(kind)
        if blocking is None:
            blocking = question_kind in BLOCKING_QUESTION_KINDS
        now = self.clock.now()
        remind_at = now + parse_duration(self.config.reminders_first_after)
        pause_at = now + parse_duration(self.config.reminders_pause_after)
        question_id = f"PQ-{uuid.uuid4().hex[:12]}"
        posted = self._has_open_posted(project_id, stage_key)
        message_id = None
        if not posted:
            message_id = self._send_question(
                question_id, channel_id, thread_id, prompt_plain, options
            )
        question = PendingQuestion(
            id=question_id,
            project_id=project_id,
            stage_key=stage_key,
            kind=kind,
            blocking=blocking,
            prompt_plain=prompt_plain,
            detail_ref=None,
            options=tuple(options),
            allowed_approvers=tuple(allowed_approvers),
            message_id=message_id,
            asked_at=now,
            remind_at=remind_at,
            pause_at=pause_at,
            answer=None,
            answered_by=None,
            answered_at=None,
            resume_token=resume_token,
        )
        self._insert(question, channel_id, thread_id, job_id)
        if job_id:
            self.job_store.finish_job(job_id, JobStatus.WAITING_HUMAN)
        self._mark_waiting(project_id)
        return question

    def answer(self, question_id: str, option: str, user_id: int) -> AnswerResult:
        question = self.get(question_id)
        if question is None:
            raise KeyError(question_id)
        if user_id not in question.allowed_approvers:
            self.discord.reply_ephemeral(user_id, FORBIDDEN)
            return AnswerResult(False, False, None, None)
        if question.answer is not None:
            return AnswerResult(True, True, question.answer, self._resume_job_id(question_id))
        now = self.clock.now()
        resume_job_id = self._enqueue_resume(question, user_id)
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE pending_questions
                SET answer = ?, answered_by = ?, answered_at = ?, resume_job_id = ?
                WHERE id = ? AND answer IS NULL
                """,
                (option, user_id, dump_dt(now), resume_job_id, question_id),
            )
        self._post_next(question.project_id, question.stage_key)
        return AnswerResult(True, False, option, resume_job_id)

    def get(self, question_id: str) -> PendingQuestion | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM pending_questions WHERE id = ?",
                (question_id,),
            ).fetchone()
        if row is None:
            return None
        return _question_from_row(row)

    def tick(self) -> tuple[str, ...]:
        events: list[str] = []
        now = self.clock.now()
        for row in self._rows("answer IS NULL AND message_id IS NOT NULL"):
            if row["paused"]:
                continue
            if load_dt(row["pause_at"]) <= now:
                self._pause_project(row["project_id"])
                with connect(self.db_path) as conn:
                    conn.execute(
                        "UPDATE pending_questions SET paused = 1 WHERE id = ?",
                        (row["id"],),
                    )
                events.append("paused")
                continue
            if not row["reminded"] and load_dt(row["remind_at"]) <= now:
                self.discord.send(
                    row["channel_id"],
                    f"Recordatorio: {row['prompt_plain']}",
                    thread_id=row["thread_id"],
                )
                with connect(self.db_path) as conn:
                    conn.execute(
                        "UPDATE pending_questions SET reminded = 1 WHERE id = ?",
                        (row["id"],),
                    )
                events.append("reminded")
        return tuple(events)

    def _send_question(self, question_id, channel_id, thread_id, prompt, options) -> int:
        buttons = tuple(Button(build_custom_id("pq", question_id, option), option) for option in options)
        return self.discord.send_buttons(channel_id, prompt, buttons, thread_id=thread_id)

    def _has_open_posted(self, project_id: str, stage_key: str) -> bool:
        with connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT id FROM pending_questions
                WHERE project_id = ? AND stage_key = ? AND answer IS NULL AND message_id IS NOT NULL
                """,
                (project_id, stage_key),
            ).fetchone()
        return row is not None

    def _mark_waiting(self, project_id: str) -> None:
        project = self.projects.get_project(project_id)
        if project is None:
            return
        if project.state in {ProjectState.WAITING_HUMAN, ProjectState.PAUSED}:
            return
        self.projects.save_project(
            _replace_state(project, ProjectState.WAITING_HUMAN, self.clock.now())
        )

    def _pause_project(self, project_id: str) -> None:
        project = self.projects.get_project(project_id)
        if project is None:
            return
        self.projects.save_project(_replace_state(project, ProjectState.PAUSED, self.clock.now()))

    def _enqueue_resume(self, question: PendingQuestion, user_id: int) -> str:
        origin = None
        job_id = self._source_job_id(question.id)
        if job_id:
            origin = self.job_store.get_job(job_id)
        channel_id, thread_id = self._location(question.id)
        if origin is not None:
            request = JobRequest.create(
                instance_name=origin.instance_name,
                message_id=f"resume-{question.id}",
                guild_id=origin.guild_id,
                channel_id=origin.channel_id,
                author_id=str(user_id),
                prompt=f"resume:{question.resume_token}",
                brain=origin.brain,
                workspace_dir=origin.workspace_dir,
                thread_id=origin.thread_id,
            )
        else:
            request = JobRequest.create(
                instance_name="code-mode",
                message_id=f"resume-{question.id}",
                guild_id="0",
                channel_id=str(channel_id),
                author_id=str(user_id),
                prompt=f"resume:{question.resume_token}",
                brain="code",
                workspace_dir="/tmp/code-mode",
                thread_id=str(thread_id) if thread_id is not None else None,
            )
        stored, admitted, _reason = self.job_store.admit_job(request)
        if not admitted or stored is None:
            raise RuntimeError("no se pudo encolar la reanudación")
        return stored.job_id

    def _post_next(self, project_id: str, stage_key: str) -> None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT * FROM pending_questions
                WHERE project_id = ? AND stage_key = ? AND answer IS NULL AND message_id IS NULL
                ORDER BY asked_at, id
                LIMIT 1
                """,
                (project_id, stage_key),
            ).fetchone()
        if row is None:
            return
        options = tuple(json.loads(row["options_json"]))
        message_id = self._send_question(
            row["id"], row["channel_id"], row["thread_id"], row["prompt_plain"], options
        )
        with connect(self.db_path) as conn:
            conn.execute(
                "UPDATE pending_questions SET message_id = ? WHERE id = ?",
                (message_id, row["id"]),
            )

    def _insert(self, question: PendingQuestion, channel_id: int, thread_id: int | None, job_id: str | None) -> None:
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO pending_questions (
                    id, project_id, stage_key, kind, blocking, prompt_plain, detail_ref,
                    options_json, approvers_json, message_id, asked_at, remind_at, pause_at,
                    answer, answered_by, answered_at, resume_token, reminded, paused,
                    channel_id, thread_id, job_id, resume_job_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, 0, 0, ?, ?, ?, NULL)
                """,
                (
                    question.id,
                    question.project_id,
                    question.stage_key,
                    question.kind,
                    1 if question.blocking else 0,
                    question.prompt_plain,
                    question.detail_ref,
                    json.dumps(list(question.options)),
                    json.dumps(list(question.allowed_approvers)),
                    question.message_id,
                    dump_dt(question.asked_at),
                    dump_dt(question.remind_at),
                    dump_dt(question.pause_at),
                    question.resume_token,
                    channel_id,
                    thread_id,
                    job_id,
                ),
            )

    def _resume_job_id(self, question_id: str) -> str | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT resume_job_id FROM pending_questions WHERE id = ?",
                (question_id,),
            ).fetchone()
        if row is None:
            return None
        return row["resume_job_id"]

    def _source_job_id(self, question_id: str) -> str | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT job_id FROM pending_questions WHERE id = ?",
                (question_id,),
            ).fetchone()
        if row is None:
            return None
        return row["job_id"]

    def _location(self, question_id: str) -> tuple[int, int | None]:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT channel_id, thread_id FROM pending_questions WHERE id = ?",
                (question_id,),
            ).fetchone()
        return row["channel_id"], row["thread_id"]

    def _rows(self, where: str) -> list:
        with connect(self.db_path) as conn:
            return conn.execute(f"SELECT * FROM pending_questions WHERE {where} ORDER BY asked_at, id").fetchall()

    def _init_db(self) -> None:
        with connect(self.db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS pending_questions (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    stage_key TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    blocking INTEGER NOT NULL,
                    prompt_plain TEXT NOT NULL,
                    detail_ref TEXT,
                    options_json TEXT NOT NULL,
                    approvers_json TEXT NOT NULL,
                    message_id INTEGER,
                    asked_at TEXT NOT NULL,
                    remind_at TEXT NOT NULL,
                    pause_at TEXT NOT NULL,
                    answer TEXT,
                    answered_by INTEGER,
                    answered_at TEXT,
                    resume_token TEXT NOT NULL,
                    reminded INTEGER NOT NULL DEFAULT 0,
                    paused INTEGER NOT NULL DEFAULT 0,
                    channel_id INTEGER NOT NULL,
                    thread_id INTEGER,
                    job_id TEXT,
                    resume_job_id TEXT
                );
                """
            )


def _replace_state(project, state: ProjectState, now):
    from dataclasses import replace

    return replace(project, state=state, updated_at=now)


def _question_from_row(row) -> PendingQuestion:
    return PendingQuestion(
        id=row["id"],
        project_id=row["project_id"],
        stage_key=row["stage_key"],
        kind=row["kind"],
        blocking=bool(row["blocking"]),
        prompt_plain=row["prompt_plain"],
        detail_ref=row["detail_ref"],
        options=tuple(json.loads(row["options_json"])),
        allowed_approvers=tuple(json.loads(row["approvers_json"])),
        message_id=row["message_id"],
        asked_at=load_dt(row["asked_at"]),
        remind_at=load_dt(row["remind_at"]),
        pause_at=load_dt(row["pause_at"]),
        answer=row["answer"],
        answered_by=row["answered_by"],
        answered_at=load_dt(row["answered_at"]),
        resume_token=row["resume_token"],
    )

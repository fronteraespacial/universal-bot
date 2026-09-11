"""Durable SQLite-backed store for jobs, deduplication, FIFO serialization, and outbox delivery."""

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple
import json
import sqlite3
import time
import uuid

from universal_bot.contracts import DeliveryStatus, JobRequest, JobResult, JobStatus


class JobStore:
    """Thread-safe and crash-safe transactional store for Universal Bot."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.execute("PRAGMA foreign_keys=ON;")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                instance_name TEXT NOT NULL,
                message_id TEXT NOT NULL,
                guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                thread_id TEXT,
                author_id TEXT NOT NULL,
                prompt TEXT NOT NULL,
                brain TEXT NOT NULL,
                workspace_dir TEXT NOT NULL,
                status TEXT NOT NULL,
                created_ts REAL NOT NULL,
                deadline_ts REAL NOT NULL,
                claimed_ts REAL,
                completed_ts REAL,
                lease_owner TEXT,
                lease_ts REAL,
                exit_code INTEGER,
                output TEXT DEFAULT '',
                error TEXT DEFAULT '',
                UNIQUE(instance_name, message_id)
            );

            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
            CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_ts);
            CREATE INDEX IF NOT EXISTS idx_jobs_channel ON jobs(channel_id);

            CREATE TABLE IF NOT EXISTS mutex_locks (
                resource_key TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                acquired_ts REAL NOT NULL,
                FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS outbox (
                outbox_id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                thread_id TEXT,
                message_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                created_ts REAL NOT NULL,
                delivered_ts REAL,
                last_error TEXT,
                FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_outbox_status ON outbox(status);
            """)

    def admit_job(self, req: JobRequest, max_pending: int = 20) -> Tuple[Optional[JobRequest], bool, str]:
        """Atomically admit a new job with deduplication by (instance_name, message_id) and queue bounds."""
        with self._conn() as conn:
            # Check for existing message_id
            row = conn.execute(
                "SELECT * FROM jobs WHERE instance_name = ? AND message_id = ?",
                (req.instance_name, req.message_id),
            ).fetchone()

            if row:
                existing = self._row_to_job(row)
                return existing, False, "duplicate_message_id"

            # Check queue capacity
            count_row = conn.execute(
                "SELECT COUNT(*) as cnt FROM jobs WHERE status IN (?, ?, ?)",
                (JobStatus.QUEUED.value, JobStatus.CLAIMED.value, JobStatus.RUNNING.value),
            ).fetchone()
            active_count = count_row["cnt"] if count_row else 0
            if active_count >= max_pending:
                return None, False, "queue_full"

            # Insert new job
            conn.execute(
                """
                INSERT INTO jobs (
                    job_id, instance_name, message_id, guild_id, channel_id, thread_id,
                    author_id, prompt, brain, workspace_dir, status, created_ts, deadline_ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    req.job_id,
                    req.instance_name,
                    req.message_id,
                    req.guild_id,
                    req.channel_id,
                    req.thread_id,
                    req.author_id,
                    req.prompt,
                    req.brain,
                    req.workspace_dir,
                    JobStatus.QUEUED.value,
                    req.created_ts,
                    req.deadline_ts,
                ),
            )
            return req, True, "admitted"

    def get_job(self, job_id: str) -> Optional[JobRequest]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if not row:
                return None
            return self._row_to_job(row)

    def get_job_status(self, job_id: str) -> Optional[JobStatus]:
        with self._conn() as conn:
            row = conn.execute("SELECT status FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if not row:
                return None
            return JobStatus(row["status"])

    def claim_next_job(
        self,
        lease_owner: str,
        max_concurrent: int = 2,
        enforce_channel_mutex: bool = True,
    ) -> Optional[JobRequest]:
        """Claim the next queued job in strict FIFO order, respecting conversation mutex and capacity."""
        now = time.time()
        with self._conn() as conn:
            # Check worker concurrency
            active_row = conn.execute(
                "SELECT COUNT(*) as cnt FROM jobs WHERE lease_owner = ? AND status IN (?, ?)",
                (lease_owner, JobStatus.CLAIMED.value, JobStatus.RUNNING.value),
            ).fetchone()
            if active_row and active_row["cnt"] >= max_concurrent:
                return None

            # Get queued candidates ordered by FIFO
            candidates = conn.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY created_ts ASC",
                (JobStatus.QUEUED.value,),
            ).fetchall()

            for row in candidates:
                job_id = row["job_id"]
                channel_id = row["channel_id"]
                workspace_dir = row["workspace_dir"]

                res_key_channel = f"channel:{channel_id}"
                res_key_ws = f"ws:{workspace_dir}"

                if enforce_channel_mutex:
                    # Check if channel or workspace is locked by another job
                    locked = conn.execute(
                        "SELECT resource_key FROM mutex_locks WHERE resource_key IN (?, ?)",
                        (res_key_channel, res_key_ws),
                    ).fetchone()
                    if locked:
                        continue  # Skip this job for now; preserve FIFO per conversation

                    # Acquire mutex
                    conn.execute(
                        "INSERT INTO mutex_locks (resource_key, job_id, acquired_ts) VALUES (?, ?, ?)",
                        (res_key_channel, job_id, now),
                    )
                    conn.execute(
                        "INSERT INTO mutex_locks (resource_key, job_id, acquired_ts) VALUES (?, ?, ?)",
                        (res_key_ws, job_id, now),
                    )

                # Claim job
                conn.execute(
                    """
                    UPDATE jobs SET
                        status = ?,
                        lease_owner = ?,
                        claimed_ts = ?,
                        lease_ts = ?
                    WHERE job_id = ? AND status = ?
                    """,
                    (
                        JobStatus.CLAIMED.value,
                        lease_owner,
                        now,
                        now,
                        job_id,
                        JobStatus.QUEUED.value,
                    ),
                )
                return self._row_to_job(row)

        return None

    def start_job(self, job_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE jobs SET status = ?, lease_ts = ? WHERE job_id = ? AND status = ?",
                (JobStatus.RUNNING.value, time.time(), job_id, JobStatus.CLAIMED.value),
            )
            return cur.rowcount > 0

    def touch_job_lease(self, job_id: str, lease_owner: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE jobs SET lease_ts = ? WHERE job_id = ? AND lease_owner = ? AND status IN (?, ?)",
                (time.time(), job_id, lease_owner, JobStatus.CLAIMED.value, JobStatus.RUNNING.value),
            )
            return cur.rowcount > 0

    def finish_job(
        self,
        job_id: str,
        status: JobStatus,
        exit_code: Optional[int] = None,
        output: str = "",
        error: str = "",
    ) -> bool:
        """Mark a job as finished in terminal state and release all associated mutex locks."""
        now = time.time()
        with self._conn() as conn:
            # Release mutex locks
            conn.execute("DELETE FROM mutex_locks WHERE job_id = ?", (job_id,))

            cur = conn.execute(
                """
                UPDATE jobs SET
                    status = ?,
                    completed_ts = ?,
                    exit_code = ?,
                    output = ?,
                    error = ?
                WHERE job_id = ?
                """,
                (status.value, now, exit_code, output, error, job_id),
            )
            return cur.rowcount > 0

    def recover_abandoned_jobs(self, lease_timeout_s: float = 300.0) -> List[str]:
        """Find crashed or abandoned jobs whose lease expired; mark them INTERRUPTED without blind re-execution."""
        now = time.time()
        cutoff = now - lease_timeout_s
        interrupted_ids: List[str] = []

        with self._conn() as conn:
            rows = conn.execute(
                "SELECT job_id FROM jobs WHERE status IN (?, ?) AND lease_ts < ?",
                (JobStatus.CLAIMED.value, JobStatus.RUNNING.value, cutoff),
            ).fetchall()

            for row in rows:
                jid = row["job_id"]
                interrupted_ids.append(jid)
                conn.execute("DELETE FROM mutex_locks WHERE job_id = ?", (jid,))
                conn.execute(
                    """
                    UPDATE jobs SET
                        status = ?,
                        completed_ts = ?,
                        error = ?
                    WHERE job_id = ?
                    """,
                    (
                        JobStatus.INTERRUPTED.value,
                        now,
                        f"Worker lease expired after {lease_timeout_s}s; marked interrupted",
                        jid,
                    ),
                )

        return interrupted_ids

    # Outbox Queue
    def enqueue_outbox(
        self,
        job_id: str,
        channel_id: str,
        message_id: str,
        payload: Dict[str, Any],
        thread_id: Optional[str] = None,
    ) -> str:
        outbox_id = f"out_{uuid.uuid4().hex[:12]}"
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO outbox (
                    outbox_id, job_id, channel_id, thread_id, message_id, payload, status, created_ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    outbox_id,
                    job_id,
                    str(channel_id),
                    str(thread_id) if thread_id else None,
                    str(message_id),
                    json.dumps(payload),
                    DeliveryStatus.PENDING.value,
                    now,
                ),
            )
        return outbox_id

    def fetch_pending_outbox(self, limit: int = 10) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM outbox
                WHERE status IN (?, ?)
                ORDER BY created_ts ASC
                LIMIT ?
                """,
                (DeliveryStatus.PENDING.value, DeliveryStatus.RETRY_WAIT.value, limit),
            ).fetchall()

            results = []
            for r in rows:
                results.append({
                    "outbox_id": r["outbox_id"],
                    "job_id": r["job_id"],
                    "channel_id": r["channel_id"],
                    "thread_id": r["thread_id"],
                    "message_id": r["message_id"],
                    "payload": json.loads(r["payload"]),
                    "status": r["status"],
                    "attempts": r["attempts"],
                    "created_ts": r["created_ts"],
                })
            return results

    def mark_outbox_delivered(self, outbox_id: str) -> bool:
        now = time.time()
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE outbox SET status = ?, delivered_ts = ? WHERE outbox_id = ?",
                (DeliveryStatus.DELIVERED.value, now, outbox_id),
            )
            return cur.rowcount > 0

    def mark_outbox_failed(self, outbox_id: str, error: str, retry: bool = True) -> bool:
        new_status = DeliveryStatus.RETRY_WAIT.value if retry else DeliveryStatus.DELIVERY_FAILED.value
        with self._conn() as conn:
            cur = conn.execute(
                """
                UPDATE outbox SET
                    status = ?,
                    attempts = attempts + 1,
                    last_error = ?
                WHERE outbox_id = ?
                """,
                (new_status, error, outbox_id),
            )
            return cur.rowcount > 0

    def _row_to_job(self, row: sqlite3.Row) -> JobRequest:
        return JobRequest(
            job_id=row["job_id"],
            instance_name=row["instance_name"],
            message_id=row["message_id"],
            guild_id=row["guild_id"],
            channel_id=row["channel_id"],
            thread_id=row["thread_id"],
            author_id=row["author_id"],
            prompt=row["prompt"],
            brain=row["brain"],
            workspace_dir=row["workspace_dir"],
            created_ts=row["created_ts"],
            deadline_ts=row["deadline_ts"],
        )

"""MAIN orquestador: conversa con el usuario mientras un worker hace el trabajo pesado.

- Un mensaje nuevo en una sesión con job activo no crea otro job: va al MAIN de ese job.
- El MAIN contesta corto y simple y puede pedir una acción con una línea final
  `ACCION: {"tipo": "ninguna|steer|relanzar|frenar", "texto": "..."}` que el runtime aplica al worker.
- El MAIN es un proceso warm (WarmBrain): si llega un mensaje mientras piensa, se le hace steer en vivo.
- El estado vive en SQLite (main_jobs): si el runtime se cae, al volver retoma el worker una sola vez.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import threading
from pathlib import Path

from universal_bot.code_mode.custom_id import build_custom_id
from universal_bot.code_mode.discord_port import Button
from universal_bot.code_mode.db import connect

log = logging.getLogger(__name__)

MAIN_SYSTEM_PROMPT = """Sos el MAIN, el orquestador de una sesión de modo código en Discord.
Reglas:
- Nunca hacés el trabajo pesado vos: siempre lo delegás. El trabajo lo hace un worker aparte que ya está corriendo.
- Quedás libre para el usuario: respondés preguntas de estado leyendo el progreso del worker que te paso, recibís órdenes nuevas y se las aplicás al worker, o lo frenás.
- Le contestás al usuario en castellano rioplatense, simple y corto (una a tres oraciones), sin jerga técnica.
- Si el usuario cambia lo que quiere, delegá el cambio al worker; si el cambio es grande, relanzalo.
- Terminá SIEMPRE con una sola línea, sin nada después:
ACCION: {"tipo": "ninguna|steer|relanzar|frenar", "texto": "instrucción para el worker si aplica"}
Usá "steer" para corregir sin cortar, "relanzar" para cortar y arrancar de nuevo con la instrucción, "frenar" si el usuario pide parar.
Si la corrección es urgente o el usuario pide parar, no esperes al worker: usá "relanzar" o "frenar", que lo cortan en el acto (un steer recién llega entre pasos del worker)."""

START_TEMPLATE = "Nuevo pedido del usuario (ya lo delegué en un worker que está corriendo): {prompt}\nAvisale en una oración que arrancaste y que puede escribirte mientras tanto."
DELIVER_TEMPLATE = (
    "Mensaje nuevo del usuario: {text}\n"
    "Estado del worker: {status}\n"
    "Progreso reciente del worker:\n{progress}\n"
    "Contestale y, si hace falta, pedí una acción."
)
FINISHED_TEMPLATE = "El worker terminó. Resultado (final de su salida):\n{result}\nContale al usuario en simple qué salió. ACCION ninguna."
STOPPED_TEXT = "Frené el trabajo."
RECOVERED_TEXT = "Se reinició el sistema; retomé el trabajo donde estaba."
LOST_TEXT = "Se cayó el trabajo y no pude retomarlo. Si querés, pedímelo de nuevo."
FAILED_TEXT = "El trabajo falló y no lo pude relanzar. Si querés, pedímelo de nuevo."
CONTROL_TEXT = "Lo estoy haciendo en segundo plano. Escribime acá cuando quieras: te cuento cómo va, cambio lo que haga falta o lo freno."
_ACTIONS = {"ninguna", "steer", "relanzar", "frenar"}


def parse_main_reply(text: str) -> tuple[str, dict]:
    lines = (text or "").rstrip().splitlines()
    action = {"tipo": "ninguna"}
    if lines and lines[-1].strip().startswith("ACCION:"):
        raw = lines.pop().strip()[len("ACCION:"):].strip()
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict) and parsed.get("tipo") in _ACTIONS:
            action = {k: v for k, v in parsed.items() if k in ("tipo", "texto")}
    return "\n".join(lines).strip()[:1800], action


def compose_prompt(prompt: str, instructions) -> str:
    if not instructions:
        return prompt
    extra = "\n".join(f"- {item}" for item in instructions)
    return f"{prompt}\n\nInstrucciones nuevas del usuario (aplicalas):\n{extra}"


class ProcessWorker:
    """Worker one-shot (CLI en el sandbox). Steer = cortar y relanzar con la instrucción nueva."""

    def __init__(self, argv_for, prompt: str, *, cwd, env=None):
        self.argv_for = argv_for
        self.prompt = prompt
        self.cwd = Path(cwd)
        self.env = env
        self.proc = None
        self.runs = 0
        self._stopped = False

    def start(self):
        self.runs += 1
        self.cwd.mkdir(parents=True, exist_ok=True)
        self.log_path = self.cwd / f"worker-{self.runs}.log"
        out = open(self.log_path, "w", encoding="utf-8")
        self.proc = subprocess.Popen(
            self.argv_for(self.prompt), cwd=self.cwd, env=self.env, stdin=subprocess.DEVNULL,
            stdout=out, stderr=subprocess.STDOUT, start_new_session=True,
        )
        out.close()
        return self

    def progress(self, limit: int = 1500) -> str:
        try:
            return self.log_path.read_text(encoding="utf-8", errors="replace")[-limit:]
        except (OSError, AttributeError):
            return ""

    def poll(self) -> str:
        if self._stopped:
            return "stopped"
        if self.proc is None:
            return "failed"
        code = self.proc.poll()
        if code is None:
            return "running"
        return "done" if code == 0 else "failed"

    def _kill(self):
        if self.proc is None or self.proc.poll() is not None:
            return
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
            self.proc.wait(5)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.proc.wait(5)

    def steer(self, text: str) -> str:
        self._kill()
        self.prompt = f"{self.prompt}\n\nCAMBIO DE INSTRUCCIÓN: {text}"
        self.start()
        return "relaunch"

    def stop(self):
        self._kill()
        self._stopped = True

    def result_text(self) -> str:
        return self.progress(3000)


class WarmWorker:
    """Worker sobre un proceso warm: el steer usa el del adaptador (en vivo si el CLI lo tiene)."""

    def __init__(self, session, prompt: str, *, timeout_s: float = 1800.0):
        self.session = session
        self.prompt = prompt
        self.timeout_s = timeout_s
        self.result = None
        self._thread = None
        self._stopped = False

    def start(self):
        if not self.session.alive():
            self.session.start()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def _run(self):
        self.result = self.session.prompt(self.prompt, timeout_s=self.timeout_s)

    def progress(self, limit: int = 1500) -> str:
        turn = getattr(self.session, "_turn", None)
        if turn is not None:
            return "".join(turn.chunks)[-limit:]
        return (self.result.text if self.result else "")[-limit:]

    def poll(self) -> str:
        if self._stopped:
            return "stopped"
        if self._thread is not None and self._thread.is_alive():
            return "running"
        return "done" if self.result is not None and self.result.ok else "failed"

    def steer(self, text: str) -> str:
        return self.session.steer(text)

    def stop(self):
        self._stopped = True
        self.session.cancel()

    def result_text(self) -> str:
        return (self.result.text if self.result else "")[-3000:]


class WarmBrain:
    """El MAIN como proceso warm. Si llega un mensaje con un turno en curso, se le hace steer en vivo."""

    def __init__(self, session_factory, *, system_prompt: str = MAIN_SYSTEM_PROMPT, timeout_s: float = 120.0):
        self.session_factory = session_factory
        self.system_prompt = system_prompt
        self.timeout_s = timeout_s
        self._sessions = {}
        self._threads = {}
        self._queued: dict[str, list[str]] = {}
        self._out: list[tuple[str, str]] = []
        self._lock = threading.Lock()
        self.steered = 0

    def submit(self, key: str, text: str) -> None:
        with self._lock:
            thread = self._threads.get(key)
            if thread is not None and thread.is_alive():
                outcome = self._sessions[key].steer(text)
                if outcome not in ("no_turn", "rejected"):
                    self.steered += 1
                    return
                self._queued.setdefault(key, []).append(text)
                return
            self._launch(key, text)

    def _launch(self, key: str, text: str) -> None:
        session = self._sessions.get(key)
        first = session is None
        if first:
            session = self.session_factory()
            session.start()
            self._sessions[key] = session
        prompt = f"{self.system_prompt}\n\n{text}" if first else text
        thread = threading.Thread(target=self._run, args=(key, session, prompt), daemon=True)
        self._threads[key] = thread
        thread.start()

    def _run(self, key, session, prompt):
        try:
            result = session.prompt(prompt, timeout_s=self.timeout_s)
            text = result.text if result.ok else ""
        except Exception as exc:  # el MAIN caído no tumba el runtime
            log.warning("MAIN %s falló: %s", key, type(exc).__name__)
            text = ""
        with self._lock:
            if text:
                self._out.append((key, text))
            pending = self._queued.pop(key, [])
            if pending:
                self._launch(key, "\n".join(pending))

    def drain(self) -> list[tuple[str, str]]:
        with self._lock:
            out, self._out = self._out, []
        return out

    def close(self) -> None:
        for session in self._sessions.values():
            session.close()
        self._sessions.clear()


class Orchestrator:
    def __init__(self, db_path, *, clock, brain, worker_factory, max_worker_restarts: int = 1):
        self.db_path = Path(db_path)
        self.clock = clock
        self.brain = brain
        self.worker_factory = worker_factory
        self.max_worker_restarts = max_worker_restarts
        self.workers: dict[str, object] = {}
        self.port = None
        self.app = None
        self._recovered = False
        with connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS main_jobs (
                    job_id TEXT PRIMARY KEY,
                    session_key TEXT NOT NULL,
                    guild_id INTEGER,
                    channel_id INTEGER NOT NULL,
                    thread_id INTEGER,
                    prompt TEXT NOT NULL,
                    instructions TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL,
                    restarts INTEGER NOT NULL DEFAULT 0,
                    reply_to INTEGER,
                    reply_channel INTEGER,
                    reply_thread INTEGER,
                    job_dir TEXT NOT NULL,
                    created_ts REAL NOT NULL,
                    updated_ts REAL NOT NULL
                )
                """
            )
            have = {row[1] for row in conn.execute("PRAGMA table_info(main_jobs)")}
            for name, kind in (("author_id", "INTEGER"), ("origin_message_id", "INTEGER"), ("project_id", "TEXT")):
                if name not in have:
                    conn.execute(f"ALTER TABLE main_jobs ADD COLUMN {name} {kind}")

    # --- SQLite ---------------------------------------------------------
    def job(self, job_id: str) -> dict | None:
        with connect(self.db_path) as conn:
            row = conn.execute("SELECT * FROM main_jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["instructions"] = json.loads(data["instructions"])
        return data

    def running_for(self, session_key: str) -> dict | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT job_id FROM main_jobs WHERE session_key = ? AND status = 'running' ORDER BY created_ts DESC LIMIT 1",
                (session_key,),
            ).fetchone()
        return self.job(row["job_id"]) if row else None

    def _update(self, job_id: str, **fields) -> None:
        if "instructions" in fields:
            fields["instructions"] = json.dumps(fields["instructions"], ensure_ascii=False)
        fields["updated_ts"] = self.clock.now().timestamp()
        cols = ", ".join(f"{name} = ?" for name in fields)
        with connect(self.db_path) as conn:
            conn.execute(f"UPDATE main_jobs SET {cols} WHERE job_id = ?", (*fields.values(), job_id))

    # --- ciclo ----------------------------------------------------------
    def bind(self, port, app) -> None:
        self.port = port
        self.app = app

    def start(self, job, job_dir, prompt: str) -> None:
        now = self.clock.now().timestamp()
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO main_jobs (job_id, session_key, guild_id, channel_id, thread_id, prompt, status,
                    reply_to, reply_channel, reply_thread, job_dir, created_ts, updated_ts, author_id, origin_message_id)
                VALUES (?, ?, ?, ?, ?, ?, 'running', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (job.job_id, job.session_key, job.guild_id, job.channel_id, job.thread_id, prompt, job.message_id,
                 job.channel_id, job.thread_id, str(job_dir), now, now, job.author.id, job.message_id),
            )
        self.workers[job.job_id] = self.worker_factory(job.job_id, prompt).start()
        self.port.send_buttons(
            job.channel_id,
            CONTROL_TEXT,
            (Button(build_custom_id("main", job.job_id, "frenar"), "Frenar"),),
            thread_id=job.thread_id,
        )
        self.brain.submit(job.job_id, START_TEMPLATE.format(prompt=prompt))
        self.app.close_job(job, job_dir, status="running", active_step="main", summary="delegado en un worker")

    def deliver(self, job, job_dir) -> bool:
        row = self.running_for(job.session_key)
        if row is None:
            return False
        worker = self.workers.get(row["job_id"])
        status = worker.poll() if worker is not None else "sin worker"
        progress = (worker.progress() if worker is not None else "") or "(todavía sin salida)"
        self._update(row["job_id"], reply_to=job.message_id, reply_channel=job.channel_id, reply_thread=job.thread_id)
        self.brain.submit(row["job_id"], DELIVER_TEMPLATE.format(text=job.prompt, status=status, progress=progress))
        self.app.close_job(job, job_dir, status="done", active_step="main-msg", summary="entregado al MAIN")
        return True

    def stop(self, job_id: str) -> bool:
        row = self.job(job_id)
        if row is None or row["status"] != "running":
            return False
        worker = self.workers.pop(job_id, None)
        if worker is not None:
            worker.stop()
        self._update(job_id, status="stopped")
        self._write_state(row, "done", "frenado", STOPPED_TEXT)
        self._send(row, STOPPED_TEXT)
        return True

    def stop_location(self, channel_id: int, thread_id: int | None) -> None:
        with connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT job_id FROM main_jobs WHERE status = 'running' AND channel_id = ? AND COALESCE(thread_id, 0) = ?",
                (channel_id, thread_id or 0),
            ).fetchall()
        for row in rows:
            self.stop(row["job_id"])

    def tick(self) -> None:
        if not self._recovered:
            self._recover()
            self._recovered = True
        for job_id, worker in list(self.workers.items()):
            state = worker.poll()
            if state == "running":
                continue
            row = self.job(job_id)
            if state == "done":
                self.workers.pop(job_id, None)
                self._update(job_id, status="done")
                self._write_state(row, "done", "main-done", "listo")
                self._publish_stages(row, worker.result_text())
                self.brain.submit(job_id, FINISHED_TEMPLATE.format(result=worker.result_text()[-1500:]))
            elif state == "failed":
                self.workers.pop(job_id, None)
                if row["restarts"] < self.max_worker_restarts:
                    self._relaunch(row, row["instructions"])
                else:
                    self._update(job_id, status="failed")
                    self._write_state(row, "error", "main", FAILED_TEXT, error="worker_failed")
                    self._send(row, FAILED_TEXT)
        for job_id, raw in self.brain.drain():
            row = self.job(job_id)
            if row is None:
                continue
            reply, action = parse_main_reply(raw)
            if reply:
                self._send(row, reply, reply=True)
            self._apply(row, action)

    def _apply(self, row, action) -> None:
        kind = action.get("tipo")
        text = str(action.get("texto") or "").strip()
        if row["status"] != "running" or kind == "ninguna":
            return
        if kind == "frenar":
            self.stop(row["job_id"])
            return
        if not text:
            return
        instructions = row["instructions"] + [text]
        self._update(row["job_id"], instructions=instructions)
        worker = self.workers.get(row["job_id"])
        if kind == "steer" and worker is not None:
            worker.steer(text)
        elif kind in ("relanzar", "steer"):
            if worker is not None:
                worker.stop()
            self.workers[row["job_id"]] = self.worker_factory(row["job_id"], compose_prompt(row["prompt"], instructions)).start()

    def _publish_stages(self, row, result: str) -> None:
        """El detalle del worker va a los hilos de etapa (02-lab y, con consulta, 03-plan); el canal solo ve al MAIN."""
        publish = getattr(self.app, "publish_worker_result", None)
        if publish is None:
            return
        try:
            project_id = publish(row, result)
        except Exception as exc:  # publicar las etapas no tumba el ciclo del MAIN
            log.warning("etapas del MAIN %s: %s", row["job_id"], type(exc).__name__)
            return
        if project_id:
            self._update(row["job_id"], project_id=project_id)

    def _relaunch(self, row, instructions) -> None:
        self._update(row["job_id"], restarts=row["restarts"] + 1)
        self.workers[row["job_id"]] = self.worker_factory(row["job_id"], compose_prompt(row["prompt"], instructions)).start()

    def _recover(self) -> None:
        with connect(self.db_path) as conn:
            rows = conn.execute("SELECT job_id FROM main_jobs WHERE status = 'running'").fetchall()
        for item in rows:
            if item["job_id"] in self.workers:
                continue
            row = self.job(item["job_id"])
            if row["restarts"] >= self.max_worker_restarts:
                self._update(row["job_id"], status="failed")
                self._write_state(row, "error", "main", LOST_TEXT, error="lost_after_restart")
                self._send(row, LOST_TEXT)
                continue
            self._relaunch(row, row["instructions"])
            self._send(row, RECOVERED_TEXT)

    # --- salida ---------------------------------------------------------
    def _send(self, row, text: str, *, reply: bool = False) -> None:
        if self.port is None:
            return
        channel = row["reply_channel"] if reply and row["reply_channel"] else row["channel_id"]
        thread = row["reply_thread"] if reply else row["thread_id"]
        self.port.send(channel, text, thread_id=thread, reply_to=row["reply_to"] if reply else None)

    def _write_state(self, row, status, step, summary, error=None) -> None:
        path = Path(row["job_dir"]) / "state.json"
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {"version": 1}
        state.update(
            status=status, active_step=step, summary=summary, error=error,
            updated_ts=self.clock.now().timestamp(),
        )
        path.write_text(json.dumps(state), encoding="utf-8")

    def close(self) -> None:
        for worker in self.workers.values():
            worker.stop()
        self.workers.clear()
        self.brain.close()

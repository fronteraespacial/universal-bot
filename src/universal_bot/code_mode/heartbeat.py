"""Heartbeat del runtime. Si pasa de 60 s, FE-BOT dice que no está."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

_NAME = "runtime.heartbeat"
_FRESH_S = 20
_STALE_S = 60


def touch_heartbeat(spool: Path, clock) -> None:
    (Path(spool) / _NAME).write_text(clock.now().isoformat(), encoding="utf-8")


def heartbeat_fresh(spool: Path, clock) -> bool:
    age = _age(spool, clock)
    return age is not None and age <= _FRESH_S


def heartbeat_status(spool: Path, clock) -> str:
    age = _age(spool, clock)
    if age is None or age > _STALE_S:
        return "no disponible"
    return "ok"


def _age(spool: Path, clock) -> float | None:
    path = Path(spool) / _NAME
    if not path.is_file():
        return None
    stamped = datetime.fromisoformat(path.read_text(encoding="utf-8").strip())
    return (clock.now() - stamped).total_seconds()


class HeartbeatThread:
    """Toca el heartbeat cada `interval_s` en un hilo aparte, así un lab largo no deja al runtime «caído»."""

    def __init__(self, spool: Path, *, interval_s: float = 10.0, clock=None):
        import threading

        from universal_bot.code_mode.clock import SystemClock

        self.spool = Path(spool)
        self.interval_s = interval_s
        self.clock = clock or SystemClock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="labcode-heartbeat", daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                touch_heartbeat(self.spool, self.clock)
            except OSError:
                pass
            self._stop.wait(self.interval_s)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(5)

    def is_alive(self) -> bool:
        return self._thread.is_alive()

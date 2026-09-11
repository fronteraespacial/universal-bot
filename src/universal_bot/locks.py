"""Portable non-blocking singleton file locks for Gateway and Worker instances."""

from pathlib import Path
from typing import Optional
import os
import sys

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore

try:
    import msvcrt
except ImportError:
    msvcrt = None  # type: ignore


class SingletonLockError(Exception):
    pass


class SingletonLock:
    """Portable file-based singleton lock that prevents duplicate Gateway/Worker instances.

    Guarantees:
    - Non-blocking acquisition (fails immediately if another process holds the lock).
    - Sets FD_CLOEXEC on POSIX so spawned child processes/CLIs NEVER inherit the lock descriptor.
    - Automatic release on process exit or crash via OS kernel file handle cleanup.
    """

    def __init__(self, lock_path: Path | str):
        self.lock_path = Path(lock_path).resolve()
        self._fd: Optional[int] = None
        self._acquired = False

    def acquire(self) -> bool:
        if self._acquired:
            return True

        self.lock_path.parent.mkdir(parents=True, exist_ok=True)

        if fcntl is not None:
            # POSIX implementation with strict FD_CLOEXEC to prevent descriptor inheritance
            flags = os.O_RDWR | os.O_CREAT
            if hasattr(os, "O_CLOEXEC"):
                flags |= os.O_CLOEXEC

            fd = os.open(str(self.lock_path), flags, 0o600)

            # Ensure FD_CLOEXEC is set even if O_CLOEXEC was unavailable
            current_flags = fcntl.fcntl(fd, fcntl.F_GETFD)
            fcntl.fcntl(fd, fcntl.F_SETFD, current_flags | fcntl.FD_CLOEXEC)

            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (BlockingIOError, OSError):
                os.close(fd)
                return False

            self._fd = fd
            self._acquired = True
            # Write diagnostic PID
            try:
                os.ftruncate(fd, 0)
                os.write(fd, f"pid={os.getpid()}\n".encode("utf-8"))
            except Exception:
                pass
            return True

        elif msvcrt is not None:
            # Windows implementation
            try:
                fd = os.open(str(self.lock_path), os.O_RDWR | os.O_CREAT | os.O_BINARY, 0o600)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                self._fd = fd
                self._acquired = True
                return True
            except (BlockingIOError, OSError):
                if 'fd' in locals():
                    os.close(fd)
                return False
        else:
            raise RuntimeError("Neither fcntl nor msvcrt available for locking")

    def release(self) -> None:
        if not self._acquired or self._fd is None:
            return

        try:
            if fcntl is not None:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            elif msvcrt is not None:
                try:
                    os.lseek(self._fd, 0, os.SEEK_SET)
                    msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
                except Exception:
                    pass
        finally:
            try:
                os.close(self._fd)
            except Exception:
                pass
            self._fd = None
            self._acquired = False

    def __enter__(self) -> bool:
        return self.acquire()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()

    @property
    def is_acquired(self) -> bool:
        return self._acquired

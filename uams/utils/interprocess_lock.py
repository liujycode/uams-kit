"""Small cross-process locks with no UAMS service dependencies."""

from __future__ import annotations

import os
import time
from pathlib import Path
from threading import RLock


class LockAcquisitionError(TimeoutError):
    """Raised when a UAMS maintenance lock cannot be acquired in time."""


class InterProcessFileLock:
    """A re-entrant-in-process, OS-backed exclusive file lock.

    Windows uses ``msvcrt.locking`` and POSIX uses ``fcntl.flock``. The OS
    releases this lock if a process ends unexpectedly, avoiding stale locks.
    """

    _guards: dict[Path, RLock] = {}
    _guards_lock = RLock()

    def __init__(self, path: str | os.PathLike[str], timeout: float = 15.0, poll_interval: float = 0.05):
        self.path = Path(path).resolve()
        self.timeout = timeout
        self.poll_interval = poll_interval
        self._handle = None
        self._guard = self._guard_for(self.path)

    @classmethod
    def _guard_for(cls, path: Path) -> RLock:
        with cls._guards_lock:
            return cls._guards.setdefault(path, RLock())

    def __enter__(self) -> "InterProcessFileLock":
        self._guard.acquire()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = self.path.open("a+b")
            self._ensure_lock_byte()
            deadline = time.monotonic() + self.timeout
            while True:
                try:
                    self._lock_file()
                    return self
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise LockAcquisitionError(f"timed out acquiring UAMS lock: {self.path}") from exc
                    time.sleep(self.poll_interval)
        except Exception:
            if self._handle is not None:
                self._handle.close()
                self._handle = None
            self._guard.release()
            raise

    def __exit__(self, exc_type, exc, traceback) -> None:
        try:
            if self._handle is not None:
                self._unlock_file()
                self._handle.close()
                self._handle = None
        finally:
            self._guard.release()

    def _ensure_lock_byte(self) -> None:
        assert self._handle is not None
        self._handle.seek(0, os.SEEK_END)
        if self._handle.tell() == 0:
            self._handle.write(b"0")
            self._handle.flush()
            os.fsync(self._handle.fileno())
        self._handle.seek(0)

    def _lock_file(self) -> None:
        assert self._handle is not None
        self._handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
            return
        import fcntl
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock_file(self) -> None:
        assert self._handle is not None
        self._handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            return
        import fcntl
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)

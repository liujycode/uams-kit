"""Backward-compatible location for the dependency-free UAMS file lock."""

from uams.utils.interprocess_lock import InterProcessFileLock, LockAcquisitionError

__all__ = ["InterProcessFileLock", "LockAcquisitionError"]

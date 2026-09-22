"""Compatibility exports for the UAMS memory store."""
from uams.services.memory_store import EntryNotFound, MemoryStore, MemoryStoreError

__all__ = ["MemoryStore", "MemoryStoreError", "EntryNotFound"]

"""Coordinates every derived index after a completed memory mutation."""

from __future__ import annotations

import os
from threading import RLock
from typing import Iterable

from uams.models.index_entry import IndexEntry
from uams.models.memory_entry import MemoryEntry
from uams.services.archive_catalog import ArchiveCatalog
from uams.services.current_index import CurrentIndex
from uams.services.search_index import SearchIndex


class IndexConsistencyManager:
    """Synchronize metadata and search projections before a mutation returns.

    ``MemoryStore`` holds the cross-process lock around this method.  The local
    lock additionally protects callers sharing one manager instance.
    """

    def __init__(self, uams_root: str | os.PathLike[str]):
        self.current_index = CurrentIndex(uams_root)
        self.archive_catalog = ArchiveCatalog(uams_root)
        self.search_index = SearchIndex(uams_root)
        self._lock = RLock()

    def synchronize(
        self,
        current_entries: Iterable[IndexEntry],
        archive_entries: Iterable[IndexEntry],
        searchable_entries: Iterable[MemoryEntry],
    ) -> None:
        with self._lock:
            self.current_index.replace(current_entries)
            self.archive_catalog.replace(archive_entries)
            self.search_index.replace(searchable_entries)

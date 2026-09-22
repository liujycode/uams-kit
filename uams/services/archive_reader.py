"""On-demand reader for explicitly requested project archive entries."""

from __future__ import annotations

from typing import Any

from uams.models.memory_entry import MemoryEntry, MemoryLayer
from uams.services.archive_catalog import ArchiveCatalog
from uams.services.memory_store import EntryNotFound, MemoryStore


class ArchiveReader:
    """Load only catalog-selected archive files for one resolved project."""

    def __init__(self, memory_store: MemoryStore, archive_catalog: ArchiveCatalog | None = None):
        self._store = memory_store
        self._catalog = archive_catalog or ArchiveCatalog(memory_store.uams_root)

    def read(self, project_id: str, query: Any = None) -> list[MemoryEntry]:
        entries: list[MemoryEntry] = []
        for item in self._catalog.select(project_id, query):
            try:
                entries.append(
                    self._store.load_entry(item.entryId, MemoryLayer.PROJECT_ARCHIVE, project_id)
                )
            except EntryNotFound:
                # A catalog entry can be stale only after an interrupted manual
                # filesystem edit; it must not cause an unrelated archive read to fail.
                continue
        return entries

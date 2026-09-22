"""Metadata-only catalog used to locate archived UAMS memory on demand."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

from uams.models.index_entry import IndexEntry
from uams.models.memory_entry import MemoryLayer
from uams.services.current_index import INDEX_SCHEMA_VERSION, IndexDataError


class ArchiveCatalog:
    """Persist archive locations without indexing archived entry bodies."""

    def __init__(self, uams_root: str | os.PathLike[str]):
        self._path = Path(uams_root).resolve() / "index" / "archive-catalog.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def entries(self) -> list[IndexEntry]:
        if not self._path.exists():
            return []
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            version = payload.get("schemaVersion", 1)
            if version not in {1, INDEX_SCHEMA_VERSION}:
                raise ValueError("unsupported schema version")
            raw_entries = payload.get("entries", [])
            if not isinstance(raw_entries, list):
                raise TypeError("entries must be an array")
            return [IndexEntry.from_dict(item) for item in raw_entries]
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise IndexDataError(f"invalid archive catalog: {self._path}") from exc

    def select(self, project_id: str, query: Any = None) -> list[IndexEntry]:
        """Select archive metadata before any archive bodies are opened."""
        selected = [entry for entry in self.entries() if entry.projectId == project_id]
        if not query:
            return selected
        if isinstance(query, str):
            query = {"text": query}
        if not isinstance(query, dict):
            raise ValueError("archive query must be a string or mapping")
        entry_id = query.get("entryId")
        digest = query.get("contentDigest", query.get("digest"))
        text = query.get("title", query.get("text", query.get("query")))
        if entry_id is not None:
            selected = [entry for entry in selected if entry.entryId == entry_id]
        if digest is not None:
            selected = [entry for entry in selected if entry.contentDigest == digest]
        if text is not None:
            normalized = str(text).casefold()
            selected = [entry for entry in selected if normalized in entry.title.casefold()]
        return selected

    def replace(self, entries: Iterable[IndexEntry]) -> None:
        materialized = list(entries)
        invalid = [entry.entryId for entry in materialized if entry.layer != MemoryLayer.PROJECT_ARCHIVE.value]
        if invalid:
            raise ValueError("archive catalog can contain only project-archive entries")
        self._atomic_write({"schemaVersion": INDEX_SCHEMA_VERSION, "entries": [entry.to_dict() for entry in materialized]})

    def _atomic_write(self, data: dict) -> None:
        fd, temporary_name = tempfile.mkstemp(prefix=".archive-catalog-", suffix=".tmp", dir=self._path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
                json.dump(data, output, indent=2, ensure_ascii=False)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_name, self._path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
            raise

"""Compact index for memory entries available to default reads."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Iterable, Optional

from uams.models.index_entry import IndexEntry
from uams.models.memory_entry import MemoryLayer


INDEX_SCHEMA_VERSION = 2


class IndexDataError(RuntimeError):
    """Raised when persisted compact-index data is invalid."""


class CurrentIndex:
    """Persist metadata for global and project-active entries only."""

    def __init__(self, uams_root: str | os.PathLike[str]):
        self._path = Path(uams_root).resolve() / "index" / "current.json"
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
            raise IndexDataError(f"invalid current index: {self._path}") from exc

    def find(self, layer: MemoryLayer | str, project_id: Optional[str] = None) -> list[IndexEntry]:
        layer_value = layer.value if isinstance(layer, MemoryLayer) else str(layer)
        return [
            entry
            for entry in self.entries()
            if entry.layer == layer_value and entry.projectId == project_id
        ]

    def replace(self, entries: Iterable[IndexEntry]) -> None:
        materialized = list(entries)
        forbidden = [entry.entryId for entry in materialized if entry.layer == MemoryLayer.PROJECT_ARCHIVE.value]
        if forbidden:
            raise ValueError("current index cannot contain project-archive entries")
        self._atomic_write({"schemaVersion": INDEX_SCHEMA_VERSION, "entries": [entry.to_dict() for entry in materialized]})

    def _atomic_write(self, data: dict) -> None:
        fd, temporary_name = tempfile.mkstemp(prefix=".current-", suffix=".tmp", dir=self._path.parent)
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

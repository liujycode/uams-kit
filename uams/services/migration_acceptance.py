"""Persistence for migration acceptance records.

The acceptance file is the only durable evidence used by the write-source
state manager.  Records and temporary files are always placed under UAMS_ROOT.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from uams.models.migration_acceptance import MigrationAcceptance


class MigrationAcceptanceStore:
    """Read and atomically persist migration acceptance records."""

    def __init__(self, uams_root: str) -> None:
        self._uams_root = Path(uams_root).resolve()
        self._acceptance_dir = self._uams_root / "migration" / "acceptance"

    @property
    def acceptance_dir(self) -> Path:
        return self._acceptance_dir

    def path_for(self, manifest_id: str) -> Path:
        return self._acceptance_dir / f"{manifest_id}.json"

    def save(self, acceptance: MigrationAcceptance) -> Path:
        """Persist a record atomically and return its UAMS-local path."""
        self._acceptance_dir.mkdir(parents=True, exist_ok=True)
        destination = self.path_for(acceptance.manifestId)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{acceptance.manifestId}-", suffix=".tmp", dir=self._acceptance_dir
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump(acceptance.to_dict(), output, indent=2, ensure_ascii=False)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_name, destination)
        except Exception:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
            raise
        return destination

    persist = save

    def load(self, manifest_id: str) -> MigrationAcceptance:
        path = self.path_for(manifest_id)
        if not path.exists():
            raise FileNotFoundError(f"Acceptance record not found: {manifest_id}")
        with path.open("r", encoding="utf-8") as source:
            return MigrationAcceptance.from_dict(json.load(source))

    def exists(self, manifest_id: str) -> bool:
        return self.path_for(manifest_id).is_file()

    def is_successful(self, manifest_id: str) -> bool:
        try:
            acceptance = self.load(manifest_id)
        except (FileNotFoundError, OSError, ValueError, KeyError):
            return False
        return acceptance.is_accepted and not acceptance.failures

    is_accepted = is_successful

    def successful_manifest_ids(self) -> list[str]:
        if not self._acceptance_dir.exists():
            return []
        successful: list[str] = []
        for path in sorted(self._acceptance_dir.glob("*.json")):
            if self.is_successful(path.stem):
                successful.append(path.stem)
        return successful


# Short alias for callers that refer to the persistence component directly.
AcceptanceRecordStore = MigrationAcceptanceStore

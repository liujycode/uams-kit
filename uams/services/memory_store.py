"""UAMS 三层 Markdown 记忆的原子持久化、恢复与索引投影。"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

from uams.models.index_entry import IndexEntry, Timestamps
from uams.models.memory_entry import MemoryEntry, MemoryLayer, MemoryStatus
from uams.services.index_consistency import IndexConsistencyManager
from uams.utils.interprocess_lock import InterProcessFileLock
from uams.services.search_index import SearchIndexDataError
from uams.utils.path_normalization import compute_content_digest, generate_entry_filename


class MemoryStoreError(RuntimeError):
    pass


class EntryNotFound(MemoryStoreError, FileNotFoundError):
    pass


LayerLike = Union[MemoryLayer, str]


class MemoryStore:
    """只在 UAMS_ROOT 内保存三层记忆，并维护可重建派生索引。"""

    FRONT_MATTER_START = "---\n"
    FRONT_MATTER_END = "---\n"

    def __init__(self, uams_root: str | os.PathLike[str]):
        self._uams_root = Path(uams_root).resolve()
        self._ensure_layout()
        self._indexes = IndexConsistencyManager(self._uams_root)
        self._write_lock = InterProcessFileLock(self._uams_root / "index" / ".uams-write.lock")
        self._journal_path = self._uams_root / "audit" / "recovery-journal.jsonl"
        self._recover_interrupted_operations()

    @property
    def uams_root(self) -> Path:
        return self._uams_root

    @property
    def root(self) -> Path:
        return self._uams_root

    def layer_directory(self, layer: LayerLike, project_id: Optional[str] = None) -> Path:
        normalized = self._layer_value(layer)
        if normalized == MemoryLayer.GLOBAL.value:
            if project_id is not None:
                raise ValueError("global entries cannot have a project_id")
            return self._uams_root / "memory" / "global" / "entries"
        if not project_id:
            raise ValueError(f"{normalized} entries require a project_id")
        if normalized == MemoryLayer.PROJECT_ACTIVE.value:
            return self._uams_root / "memory" / "projects" / project_id / "active" / "entries"
        if normalized == MemoryLayer.PROJECT_ARCHIVE.value:
            return self._uams_root / "memory" / "projects" / project_id / "archive" / "entries"
        raise ValueError(f"unsupported memory layer: {layer}")

    def path_for_entry(self, entry: MemoryEntry) -> Path:
        directory = self.layer_directory(entry.layer, entry.projectId)
        return self._safe_path(directory / generate_entry_filename(entry.entryId, entry.title))

    def save_entry(self, entry: MemoryEntry) -> MemoryEntry:
        if not isinstance(entry, MemoryEntry):
            raise TypeError("entry must be a MemoryEntry")
        if entry.contentDigest is None:
            entry.contentDigest = compute_content_digest(entry.body)
        with self._write_lock:
            transaction_id = self._begin_transaction("save", {"entryId": entry.entryId})
            try:
                destination = self.path_for_entry(entry)
                destination.parent.mkdir(parents=True, exist_ok=True)
                # Publish the replacement before removing a prior location, so a
                # failed write cannot destroy the only copy of an entry.
                self._atomic_write_text(destination, self._serialize(entry))
                for old_path in self._paths_for_entry_id(entry.entryId):
                    if old_path != destination:
                        old_path.unlink(missing_ok=True)
                self._rebuild_indexes_unlocked()
            except Exception:
                self._mark_recovery_required(transaction_id)
                raise
            self._complete_transaction(transaction_id)
        return entry

    save = persist = write = save_entry

    def load_entry(self, entry_id: str, layer: Optional[LayerLike] = None, project_id: Optional[str] = None) -> MemoryEntry:
        candidates = self._paths_for_entry_id(entry_id, layer, project_id)
        if not candidates:
            raise EntryNotFound(f"memory entry not found: {entry_id}")
        return self._deserialize(candidates[0].read_text(encoding="utf-8"))

    load = get = read_entry = load_entry

    def list_entries(self, layer: Optional[LayerLike] = None, project_id: Optional[str] = None) -> list[MemoryEntry]:
        if layer is not None:
            directories = [self.layer_directory(layer, project_id)]
        elif project_id is not None:
            directories = [
                self.layer_directory(MemoryLayer.PROJECT_ACTIVE, project_id),
                self.layer_directory(MemoryLayer.PROJECT_ARCHIVE, project_id),
            ]
        else:
            directories = [
                self.layer_directory(MemoryLayer.GLOBAL),
                *(self._uams_root / "memory" / "projects").glob("*/active/entries"),
                *(self._uams_root / "memory" / "projects").glob("*/archive/entries"),
            ]
        entries: list[MemoryEntry] = []
        for directory in directories:
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.md")):
                try:
                    entries.append(self._deserialize(path.read_text(encoding="utf-8")))
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    raise MemoryStoreError(f"invalid memory entry: {path}") from exc
        return entries

    entries = all_entries = list_entries

    def delete_entry(self, entry_id: str, layer: Optional[LayerLike] = None, project_id: Optional[str] = None) -> None:
        with self._write_lock:
            transaction_id = self._begin_transaction("delete", {"entryId": entry_id})
            try:
                paths = self._paths_for_entry_id(entry_id, layer, project_id)
                if not paths:
                    raise EntryNotFound(f"memory entry not found: {entry_id}")
                for path in paths:
                    path.unlink(missing_ok=True)
                self._rebuild_indexes_unlocked()
            except Exception:
                self._mark_recovery_required(transaction_id)
                raise
            self._complete_transaction(transaction_id)

    delete = delete_entry

    def archive_entry(self, entry_id: str, project_id: Optional[str] = None) -> MemoryEntry:
        """归档项目活跃条目，完整保留结构化元数据且可从中断恢复。"""
        with self._write_lock:
            transaction_id = self._begin_transaction("archive", {"entryId": entry_id, "projectId": project_id})
            try:
                entry = self.load_entry(entry_id, MemoryLayer.PROJECT_ACTIVE, project_id)
                archived = MemoryEntry(
                    entryId=entry.entryId,
                    layer=MemoryLayer.PROJECT_ARCHIVE,
                    projectId=entry.projectId,
                    title=entry.title,
                    body=entry.body,
                    status=MemoryStatus.ARCHIVED,
                    createdAt=entry.createdAt,
                    updatedAt=datetime.now(timezone.utc),
                    contentDigest=entry.contentDigest or compute_content_digest(entry.body),
                    memoryType=entry.memoryType,
                    subject=entry.subject,
                    tags=entry.tags,
                    source=entry.source,
                    confidence=entry.confidence,
                    validUntil=entry.validUntil,
                    supersedes=entry.supersedes,
                    schemaVersion=entry.schemaVersion,
                )
                active_path = self.path_for_entry(entry)
                archive_path = self.path_for_entry(archived)
                archive_path.parent.mkdir(parents=True, exist_ok=True)
                self._atomic_write_text(archive_path, self._serialize(archived))
                active_path.unlink(missing_ok=True)
                self._rebuild_indexes_unlocked()
            except Exception:
                self._mark_recovery_required(transaction_id)
                raise
            self._complete_transaction(transaction_id)
        return archived

    archive = archive_entry_by_id = archive_entry

    def current_index(self) -> list[IndexEntry]:
        return self._indexes.current_index.entries()

    def archive_catalog(self) -> list[IndexEntry]:
        return self._indexes.archive_catalog.entries()

    def check_health(self, repair: bool = False) -> dict[str, Any]:
        """Validate every derived index and optionally rebuild it from entries."""
        with self._write_lock:
            entries = self.list_entries()
            issues = self._health_issues(entries)
            repaired = False
            if issues and repair:
                self._rebuild_indexes_unlocked(entries)
                repaired = True
                issues = self._health_issues(entries)
            return {
                "healthy": not issues,
                "repaired": repaired,
                "issues": issues,
                "entryCount": len(entries),
                "currentEntryCount": sum(entry.layer != MemoryLayer.PROJECT_ARCHIVE for entry in entries),
                "archiveEntryCount": sum(entry.layer == MemoryLayer.PROJECT_ARCHIVE for entry in entries),
            }

    health_check = check_health

    def rebuild_indexes(self) -> None:
        """Explicitly rebuild derived indexes from canonical Markdown entries."""
        with self._write_lock:
            self._rebuild_indexes_unlocked()

    def _ensure_layout(self) -> None:
        for path in (
            self._uams_root / "memory" / "global" / "entries",
            self._uams_root / "memory" / "projects",
            self._uams_root / "index",
            self._uams_root / "audit",
        ):
            path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _layer_value(layer: LayerLike) -> str:
        return layer.value if isinstance(layer, MemoryLayer) else str(layer)

    def _paths_for_entry_id(self, entry_id: str, layer: Optional[LayerLike] = None, project_id: Optional[str] = None) -> list[Path]:
        if layer is not None:
            directories = [self.layer_directory(layer, project_id)]
        else:
            directories = [
                self.layer_directory(MemoryLayer.GLOBAL),
                *(self._uams_root / "memory" / "projects").glob("*/active/entries"),
                *(self._uams_root / "memory" / "projects").glob("*/archive/entries"),
            ]
        prefix = f"{entry_id}--"
        return [path for directory in directories if directory.is_dir() for path in sorted(directory.glob(f"{prefix}*.md")) if path.is_file()]

    def _safe_path(self, path: Path) -> Path:
        resolved = path.resolve()
        try:
            resolved.relative_to(self._uams_root)
        except ValueError as exc:
            raise MemoryStoreError("memory path must remain inside UAMS_ROOT") from exc
        return resolved

    @classmethod
    def _serialize(cls, entry: MemoryEntry) -> str:
        body = entry.body if entry.body.endswith("\n") else f"{entry.body}\n"
        return cls.FRONT_MATTER_START + json.dumps(entry.to_dict(), ensure_ascii=False, sort_keys=True) + "\n" + cls.FRONT_MATTER_END + body

    @classmethod
    def _deserialize(cls, content: str) -> MemoryEntry:
        if not content.startswith(cls.FRONT_MATTER_START):
            raise ValueError("missing memory entry metadata")
        marker = content.find("\n---\n", len(cls.FRONT_MATTER_START))
        if marker < 0:
            raise ValueError("missing memory entry metadata terminator")
        metadata = json.loads(content[len(cls.FRONT_MATTER_START):marker])
        body = content[marker + len("\n---\n"):]
        metadata["body"] = body[:-1] if body.endswith("\n") else body
        return MemoryEntry.from_dict(metadata)

    def _atomic_write_text(self, destination: Path, content: str) -> None:
        fd, temporary_name = tempfile.mkstemp(prefix=f".{destination.stem}-", suffix=".tmp", dir=destination.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_name, destination)
        except Exception:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
            raise

    def _build_projections(self, entries: list[MemoryEntry]) -> tuple[list[IndexEntry], list[IndexEntry]]:
        current: list[IndexEntry] = []
        archive: list[IndexEntry] = []
        for entry in entries:
            item = IndexEntry(
                entryId=entry.entryId,
                layer=entry.layer.value,
                projectId=entry.projectId,
                title=entry.title,
                timestamps=Timestamps(entry.createdAt, entry.updatedAt),
                contentDigest=entry.contentDigest,
                storageLocation=self.path_for_entry(entry).relative_to(self._uams_root).as_posix(),
                archivedAt=entry.updatedAt if entry.layer == MemoryLayer.PROJECT_ARCHIVE else None,
                memoryType=entry.memoryType,
                subject=entry.subject,
                tags=entry.tags,
                source=entry.source,
                confidence=entry.confidence,
                validUntil=entry.validUntil,
                supersedes=entry.supersedes,
            )
            (archive if entry.layer == MemoryLayer.PROJECT_ARCHIVE else current).append(item)
        return current, archive

    def _rebuild_indexes_unlocked(self, entries: Optional[list[MemoryEntry]] = None) -> None:
        canonical_entries = entries if entries is not None else self.list_entries()
        current, archive = self._build_projections(canonical_entries)
        self._indexes.synchronize(current, archive, canonical_entries)

    @staticmethod
    def _canonical_index(entries: list[IndexEntry]) -> list[dict]:
        return sorted((entry.to_dict() for entry in entries), key=lambda item: item["entryId"])

    def _health_issues(self, entries: list[MemoryEntry]) -> list[str]:
        expected_current, expected_archive = self._build_projections(entries)
        issues: list[str] = []
        try:
            if self._canonical_index(self._indexes.current_index.entries()) != self._canonical_index(expected_current):
                issues.append("current-index-mismatch")
        except Exception:
            issues.append("current-index-invalid")
        try:
            if self._canonical_index(self._indexes.archive_catalog.entries()) != self._canonical_index(expected_archive):
                issues.append("archive-catalog-mismatch")
        except Exception:
            issues.append("archive-catalog-invalid")
        try:
            if not self._indexes.search_index.matches(entries):
                issues.append("search-index-mismatch")
        except SearchIndexDataError:
            issues.append("search-index-invalid")
        return issues

    def _begin_transaction(self, operation: str, details: dict[str, Any]) -> str:
        transaction_id = f"memory-{uuid.uuid4()}"
        self._append_journal({
            "transactionId": transaction_id,
            "phase": "begin",
            "operation": operation,
            "details": details,
        })
        return transaction_id

    def _complete_transaction(self, transaction_id: str) -> None:
        self._append_journal({"transactionId": transaction_id, "phase": "complete"})

    def _mark_recovery_required(self, transaction_id: str) -> None:
        self._append_journal({"transactionId": transaction_id, "phase": "recovery-required"})

    def _append_journal(self, event: dict[str, Any]) -> None:
        self._journal_path.parent.mkdir(parents=True, exist_ok=True)
        record = {**event, "timestamp": datetime.now(timezone.utc).isoformat()}
        with self._journal_path.open("a", encoding="utf-8", newline="\n") as output:
            output.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            output.flush()
            os.fsync(output.fileno())

    def _recover_interrupted_operations(self) -> None:
        if not self._journal_path.is_file():
            return
        try:
            events = [json.loads(line) for line in self._journal_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except (OSError, ValueError) as exc:
            raise MemoryStoreError(f"invalid recovery journal: {self._journal_path}") from exc
        pending: dict[str, dict] = {}
        for event in events:
            transaction_id = event.get("transactionId")
            if not transaction_id:
                continue
            if event.get("phase") == "begin":
                pending[transaction_id] = event
            elif event.get("phase") in {"complete", "recovered"}:
                pending.pop(transaction_id, None)
        if not pending:
            return
        with self._write_lock:
            for event in pending.values():
                if event.get("operation") == "archive":
                    details = event.get("details", {})
                    entry_id = details.get("entryId")
                    project_id = details.get("projectId")
                    if entry_id:
                        archive_paths = self._paths_for_entry_id(entry_id, MemoryLayer.PROJECT_ARCHIVE, project_id)
                        active_paths = self._paths_for_entry_id(entry_id, MemoryLayer.PROJECT_ACTIVE, project_id)
                        if archive_paths and active_paths:
                            for active_path in active_paths:
                                active_path.unlink(missing_ok=True)
            self._rebuild_indexes_unlocked()
            for transaction_id in pending:
                self._append_journal({"transactionId": transaction_id, "phase": "recovered"})

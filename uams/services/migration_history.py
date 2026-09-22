"""Read-only inspection of migration copies stored inside UAMS."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from uams.services.migration_acceptance import MigrationAcceptanceStore


class MigrationHistoryError(RuntimeError):
    """Raised when a stored migration manifest or its copies are invalid."""


class MigrationHistoryReader:
    """Expose accepted migration metadata without reopening a protected source.

    This reader only inspects files copied below ``UAMS_ROOT/migration``.  It
    deliberately returns source-manifest metadata, not historical file bodies,
    so discovery cannot accidentally inject stale or sensitive content into an
    active AI context.
    """

    def __init__(self, uams_root: str | Path, manifest_id: str):
        self._root = Path(uams_root).resolve()
        self.manifest_id = str(manifest_id).strip()
        if not self.manifest_id:
            raise MigrationHistoryError("migration manifest ID is required")
        self._manifest_path = self._root / "migration" / "source-manifests" / f"{self.manifest_id}.json"
        self._copies_root = self._root / "migration" / "copies" / self.manifest_id
        self._acceptances = MigrationAcceptanceStore(str(self._root))

    def summary(self) -> dict[str, Any]:
        manifest = self._manifest()
        try:
            acceptance = self._acceptances.load(self.manifest_id)
        except (FileNotFoundError, OSError, ValueError, KeyError) as exc:
            raise MigrationHistoryError(f"migration acceptance is unavailable: {self.manifest_id}") from exc
        return {
            "manifestId": self.manifest_id,
            "accepted": acceptance.is_accepted,
            "validatedEntryCount": acceptance.validatedEntryCount,
            "manifestEntryCount": len(manifest["entries"]),
            "copyRootExists": self._copies_root.is_dir(),
            "copyRoot": str(self._copies_root),
            "failures": [failure.to_dict() for failure in acceptance.failures],
        }

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        normalized_query = self._normalize(query)
        if not normalized_query:
            raise MigrationHistoryError("migration search query is required")
        matches: list[dict[str, Any]] = []
        for entry in self._manifest()["entries"]:
            relative_path = str(entry.get("relativePath", ""))
            if normalized_query not in self._normalize(relative_path):
                continue
            copied = self._safe_copy_path(relative_path)
            matches.append({
                "relativePath": relative_path,
                "byteLength": entry.get("byteLength"),
                "sha256": entry.get("sha256"),
                "copyPresent": copied.is_file(),
            })
            if len(matches) >= max(1, limit):
                break
        return matches

    def read_text(self, relative_path: str, max_chars: int = 8_000) -> dict[str, Any]:
        """Return a bounded, credential-redacted text preview of one copied file."""
        entry = next(
            (item for item in self._manifest()["entries"] if item.get("relativePath") == relative_path),
            None,
        )
        if entry is None:
            raise MigrationHistoryError("migration file is not present in the accepted manifest")
        target = self._safe_copy_path(relative_path)
        if not target.is_file():
            raise MigrationHistoryError("accepted migration copy is missing")
        if max_chars < 1 or max_chars > 20_000:
            raise MigrationHistoryError("max_chars must be between 1 and 20000")
        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise MigrationHistoryError("migration copy is not UTF-8 text") from exc
        preview = self._redact(content[:max_chars])
        return {
            "relativePath": relative_path,
            "byteLength": entry.get("byteLength"),
            "sha256": entry.get("sha256"),
            "content": preview,
            "truncated": len(content) > max_chars,
        }

    def _manifest(self) -> dict[str, Any]:
        try:
            payload = json.loads(self._manifest_path.read_text(encoding="utf-8"))
            if payload.get("manifestId") != self.manifest_id or not isinstance(payload.get("entries"), list):
                raise ValueError("invalid migration manifest")
            return payload
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise MigrationHistoryError(f"invalid migration manifest: {self._manifest_path}") from exc

    def _safe_copy_path(self, relative_path: str) -> Path:
        target = (self._copies_root / relative_path).resolve()
        try:
            target.relative_to(self._copies_root.resolve())
        except ValueError as exc:
            raise MigrationHistoryError("migration copy path escapes UAMS root") from exc
        return target

    @staticmethod
    def _redact(content: str) -> str:
        redacted = re.sub(r"(?i)(sk-[a-z0-9_-]{8,})", "[REDACTED_API_KEY]", content)
        redacted = re.sub(
            r"(?im)^(\s*(?:api[_-]?key|password|secret|access[_-]?token)\s*[:=]\s*)([^\s#]+)",
            r"\1[REDACTED]",
            redacted,
        )
        return redacted

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(value).casefold())

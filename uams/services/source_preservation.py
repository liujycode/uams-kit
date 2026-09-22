"""Read-only verification that the legacy source still matches its manifest.

All output from this service is written below UAMS_ROOT.  The source is only
opened for existence, length, and digest checks; this module has no operation
that can modify the legacy tree.

Validates: Requirement 1.4
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

from uams.adapters.legacy_source_adapter import LegacySourceAdapter
from uams.services.source_discovery import SourceManifest


@dataclass
class SourcePreservationDifference:
    """One difference between a manifest entry and the current source."""

    relativePath: str
    differenceType: str
    expected: Any = None
    actual: Any = None

    def to_dict(self) -> dict:
        return {
            "relativePath": self.relativePath,
            "differenceType": self.differenceType,
            "expected": self.expected,
            "actual": self.actual,
        }


@dataclass
class SourcePreservationReport:
    """Result of checking every manifest entry against the source."""

    manifestId: str
    checkedEntryCount: int
    checkedAt: datetime
    differences: List[SourcePreservationDifference] = field(default_factory=list)

    @property
    def is_preserved(self) -> bool:
        return not self.differences

    @property
    def is_valid(self) -> bool:
        """Alias used by callers that treat the report as a validation result."""
        return self.is_preserved

    def to_dict(self) -> dict:
        return {
            "manifestId": self.manifestId,
            "checkedEntryCount": self.checkedEntryCount,
            "checkedAt": self.checkedAt.isoformat(),
            "isPreserved": self.is_preserved,
            "differences": [difference.to_dict() for difference in self.differences],
        }


class SourcePreservationService:
    """Check source preservation without ever writing to the source."""

    def __init__(
        self,
        uams_root: str,
        source_root: Optional[str] = None,
        audit_log_path: Optional[str] = None,
    ) -> None:
        self._uams_root = Path(uams_root).resolve()
        self._source_root = source_root
        # The default audit path is deliberately inside UAMS_ROOT.
        self._audit_log_path = (
            Path(audit_log_path).resolve()
            if audit_log_path
            else self._uams_root / "audit" / "migration.jsonl"
        )
        self._last_report: Optional[SourcePreservationReport] = None

    @property
    def last_report(self) -> Optional[SourcePreservationReport]:
        return self._last_report

    @property
    def audit_log_path(self) -> Path:
        return self._audit_log_path

    def check(self, manifest: SourceManifest) -> SourcePreservationReport:
        """Compare source existence, byte length, and SHA-256 for each entry.

        Differences are logged individually.  No repair, copy-back, overwrite,
        or other source mutation is attempted.
        """
        source_root = self._source_root or manifest.source_root
        adapter = LegacySourceAdapter(source_root)
        differences: List[SourcePreservationDifference] = []

        for entry in manifest.entries:
            if not adapter.file_exists(entry.relativePath):
                differences.append(
                    SourcePreservationDifference(
                        relativePath=entry.relativePath,
                        differenceType="missing",
                        expected="present",
                        actual="missing",
                    )
                )
                continue

            try:
                content = adapter.read_file(entry.relativePath)
            except (OSError, ValueError) as exc:
                differences.append(
                    SourcePreservationDifference(
                        relativePath=entry.relativePath,
                        differenceType="read_error",
                        expected="readable",
                        actual=str(exc),
                    )
                )
                continue

            actual_length = len(content)
            if actual_length != entry.byteLength:
                differences.append(
                    SourcePreservationDifference(
                        relativePath=entry.relativePath,
                        differenceType="byte_length_mismatch",
                        expected=entry.byteLength,
                        actual=actual_length,
                    )
                )

            actual_sha256 = adapter.compute_digest(content)
            if actual_sha256 != entry.sha256:
                differences.append(
                    SourcePreservationDifference(
                        relativePath=entry.relativePath,
                        differenceType="sha256_mismatch",
                        expected=entry.sha256,
                        actual=actual_sha256,
                    )
                )

        report = SourcePreservationReport(
            manifestId=manifest.manifest_id,
            checkedEntryCount=len(manifest.entries),
            checkedAt=datetime.now(timezone.utc),
            differences=differences,
        )
        self._last_report = report
        for difference in differences:
            self._log_difference(report, difference)
        return report

    # Descriptive aliases keep the service convenient for callers of Phase 3.
    verify = check
    check_manifest = check

    def _log_difference(
        self,
        report: SourcePreservationReport,
        difference: SourcePreservationDifference,
    ) -> None:
        entry = {
            "eventType": "source_preservation_difference",
            "timestamp": report.checkedAt.isoformat(),
            "manifestId": report.manifestId,
            **difference.to_dict(),
        }
        self._audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._audit_log_path.open("a", encoding="utf-8") as log:
            log.write(json.dumps(entry, ensure_ascii=False) + "\n")


# Alternate name used by some integrations.
SourcePreservationChecker = SourcePreservationService

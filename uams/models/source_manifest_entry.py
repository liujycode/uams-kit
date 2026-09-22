"""
SourceManifestEntry - Immutable baseline for migration source files

Validates: Requirements 3.1
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class SourceManifestEntry:
    """
    Immutable baseline record for a single importable source file.
    
    Attributes:
        relativePath: Normalized relative path from source root
        byteLength: File size in bytes
        sha256: SHA-256 content digest
        discoveredAt: Timestamp when the file was discovered
    """
    relativePath: str = ""
    byteLength: int = 0
    sha256: str = ""
    discoveredAt: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON persistence."""
        return {
            "relativePath": self.relativePath,
            "byteLength": self.byteLength,
            "sha256": self.sha256,
            "discoveredAt": self.discoveredAt.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "SourceManifestEntry":
        """Deserialize from dictionary."""
        return cls(
            relativePath=data["relativePath"],
            byteLength=data["byteLength"],
            sha256=data["sha256"],
            discoveredAt=datetime.fromisoformat(data["discoveredAt"]),
        )

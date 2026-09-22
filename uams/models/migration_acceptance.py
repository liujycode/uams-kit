"""
MigrationAcceptance - Sole gate for write-source transition

Validates: Requirements 3.5, 4.1
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional
from enum import Enum


class MigrationResult(Enum):
    """Migration validation result."""
    SUCCESS = "success"
    FAILURE = "failure"


@dataclass
class MigrationFailure:
    """Details of a migration validation failure."""
    relativePath: str
    reason: str
    
    def to_dict(self) -> dict:
        return {
            "relativePath": self.relativePath,
            "reason": self.reason,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "MigrationFailure":
        return cls(
            relativePath=data["relativePath"],
            reason=data["reason"],
        )


@dataclass
class MigrationAcceptance:
    """
    Migration acceptance record - the sole gate for write-source transition.
    
    Attributes:
        manifestId: Identifier of the source manifest
        validatedEntryCount: Number of entries successfully validated
        validatedAt: Timestamp of validation completion
        result: SUCCESS or FAILURE
        failures: List of validation failures (if any)
    """
    manifestId: str = ""
    validatedEntryCount: int = 0
    validatedAt: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    result: MigrationResult = MigrationResult.FAILURE
    failures: List[MigrationFailure] = field(default_factory=list)
    
    @property
    def is_accepted(self) -> bool:
        """Check if this record is a complete, successful acceptance.

        A success result carrying failures is treated as invalid so a
        malformed or hand-edited record can never open the write-source gate.
        """
        return self.result == MigrationResult.SUCCESS and not self.failures
    
    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON persistence."""
        return {
            "manifestId": self.manifestId,
            "validatedEntryCount": self.validatedEntryCount,
            "validatedAt": self.validatedAt.isoformat(),
            "result": self.result.value,
            "failures": [f.to_dict() for f in self.failures],
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "MigrationAcceptance":
        """Deserialize from dictionary."""
        return cls(
            manifestId=data["manifestId"],
            validatedEntryCount=data["validatedEntryCount"],
            validatedAt=datetime.fromisoformat(data["validatedAt"]),
            result=MigrationResult(data["result"]),
            failures=[MigrationFailure.from_dict(f) for f in data.get("failures", [])],
        )

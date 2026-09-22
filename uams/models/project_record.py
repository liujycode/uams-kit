"""
ProjectRecord - Project registry record for UAMS

Validates: Requirements 5.1
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional
import uuid


@dataclass
class ProjectRecord:
    """
    Project registry record mapping project identity to paths and memory location.
    
    Attributes:
        projectId: Unique project identifier
        normalizedProjectPath: Normalized absolute project directory path
        normalizedWorkspaceAliases: List of normalized workspace path aliases
        memoryLocation: Path to project memory storage in UAMS
        createdAt: Timestamp when the project was registered
        updatedAt: Timestamp when the record was last updated
    """
    projectId: str = field(default_factory=lambda: str(uuid.uuid4()))
    normalizedProjectPath: str = ""
    normalizedWorkspaceAliases: List[str] = field(default_factory=list)
    memoryLocation: str = ""
    createdAt: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updatedAt: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def __post_init__(self):
        """Set memory location if not provided."""
        if not self.memoryLocation and self.projectId:
            # Memory location is always within UAMS, not in project directory
            from uams import UAMS_ROOT
            self.memoryLocation = f"{UAMS_ROOT}/memory/projects/{self.projectId}"
    
    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON persistence."""
        return {
            "projectId": self.projectId,
            "normalizedProjectPath": self.normalizedProjectPath,
            "normalizedWorkspaceAliases": self.normalizedWorkspaceAliases,
            "memoryLocation": self.memoryLocation,
            "createdAt": self.createdAt.isoformat(),
            "updatedAt": self.updatedAt.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ProjectRecord":
        """Deserialize from dictionary."""
        return cls(
            projectId=data["projectId"],
            normalizedProjectPath=data["normalizedProjectPath"],
            normalizedWorkspaceAliases=data.get("normalizedWorkspaceAliases", []),
            memoryLocation=data["memoryLocation"],
            createdAt=datetime.fromisoformat(data["createdAt"]),
            updatedAt=datetime.fromisoformat(data["updatedAt"]),
        )

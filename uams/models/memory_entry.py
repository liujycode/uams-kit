"""UAMS 的结构化长期记忆条目模型。"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
import uuid


class MemoryLayer(Enum):
    """三层记忆的存储范围与生命周期。"""

    GLOBAL = "global"
    PROJECT_ACTIVE = "project-active"
    PROJECT_ARCHIVE = "project-archive"


class MemoryStatus(Enum):
    """记忆条目的可见状态。"""

    ACTIVE = "active"
    ARCHIVED = "archived"


@dataclass
class MemoryEntry:
    """由 UAMS Gateway 管理的最小、可追溯长期记忆单元。

    新增的结构化字段均有向后兼容默认值，因此旧版 front matter 可继续读取。
    """

    # Versioned front matter lets future readers migrate fields without guessing.
    schemaVersion: int = 2
    entryId: str = field(default_factory=lambda: str(uuid.uuid4()))
    layer: MemoryLayer = MemoryLayer.GLOBAL
    projectId: Optional[str] = None
    title: str = ""
    body: str = ""
    status: MemoryStatus = MemoryStatus.ACTIVE
    createdAt: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updatedAt: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    contentDigest: Optional[str] = None
    memoryType: str = "note"
    subject: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    source: Optional[str] = None
    confidence: str = "confirmed"
    validUntil: Optional[datetime] = None
    supersedes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.schemaVersion not in {1, 2}:
            raise ValueError(f"unsupported memory entry schema version: {self.schemaVersion}")
        if self.layer == MemoryLayer.GLOBAL and self.projectId is not None:
            raise ValueError("Global entries must not have a projectId")
        if self.layer in (MemoryLayer.PROJECT_ACTIVE, MemoryLayer.PROJECT_ARCHIVE) and self.projectId is None:
            raise ValueError("Project-scoped entries must have a projectId")
        if self.layer == MemoryLayer.PROJECT_ARCHIVE and self.status != MemoryStatus.ARCHIVED:
            raise ValueError("Archive layer entries must have archived status")
        if self.layer == MemoryLayer.PROJECT_ACTIVE and self.status != MemoryStatus.ACTIVE:
            raise ValueError("Active layer entries must have active status")

        self.memoryType = str(self.memoryType or "note").strip() or "note"
        self.subject = str(self.subject).strip() if self.subject else None
        self.tags = sorted({str(tag).strip() for tag in self.tags if str(tag).strip()})
        self.source = str(self.source).strip() if self.source else None
        self.confidence = str(self.confidence or "confirmed").strip() or "confirmed"
        self.supersedes = sorted({str(entry_id).strip() for entry_id in self.supersedes if str(entry_id).strip()})

    def to_dict(self) -> dict:
        return {
            "schemaVersion": self.schemaVersion,
            "entryId": self.entryId,
            "layer": self.layer.value,
            "projectId": self.projectId,
            "title": self.title,
            "body": self.body,
            "status": self.status.value,
            "createdAt": self.createdAt.isoformat(),
            "updatedAt": self.updatedAt.isoformat(),
            "contentDigest": self.contentDigest,
            "memoryType": self.memoryType,
            "subject": self.subject,
            "tags": self.tags,
            "source": self.source,
            "confidence": self.confidence,
            "validUntil": self.validUntil.isoformat() if self.validUntil else None,
            "supersedes": self.supersedes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MemoryEntry":
        valid_until = data.get("validUntil") or data.get("valid_until")
        return cls(
            schemaVersion=int(data.get("schemaVersion", 1)),
            entryId=data["entryId"],
            layer=MemoryLayer(data["layer"]),
            projectId=data.get("projectId"),
            title=data["title"],
            body=data["body"],
            status=MemoryStatus(data["status"]),
            createdAt=datetime.fromisoformat(data["createdAt"]),
            updatedAt=datetime.fromisoformat(data["updatedAt"]),
            contentDigest=data.get("contentDigest"),
            memoryType=data.get("memoryType", data.get("type", "note")),
            subject=data.get("subject"),
            tags=data.get("tags", []),
            source=data.get("source"),
            confidence=data.get("confidence", "confirmed"),
            validUntil=datetime.fromisoformat(valid_until) if valid_until else None,
            supersedes=data.get("supersedes", []),
        )

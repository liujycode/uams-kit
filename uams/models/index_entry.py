"""Current index 与 archive catalog 的紧凑、无正文元数据模型。"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Timestamps:
    createdAt: datetime
    updatedAt: datetime

    def to_dict(self) -> dict:
        return {"createdAt": self.createdAt.isoformat(), "updatedAt": self.updatedAt.isoformat()}

    @classmethod
    def from_dict(cls, data: dict) -> "Timestamps":
        return cls(createdAt=datetime.fromisoformat(data["createdAt"]), updatedAt=datetime.fromisoformat(data["updatedAt"]))


@dataclass
class IndexEntry:
    """定位活跃或归档条目的紧凑元数据；绝不存储记忆正文。"""

    entryId: str = ""
    layer: str = ""
    projectId: Optional[str] = None
    title: str = ""
    timestamps: Optional[Timestamps] = None
    contentDigest: Optional[str] = None
    storageLocation: str = ""
    archivedAt: Optional[datetime] = None
    memoryType: str = "note"
    subject: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    source: Optional[str] = None
    confidence: str = "confirmed"
    validUntil: Optional[datetime] = None
    supersedes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "entryId": self.entryId,
            "layer": self.layer,
            "projectId": self.projectId,
            "title": self.title,
            "timestamps": self.timestamps.to_dict() if self.timestamps else None,
            "contentDigest": self.contentDigest,
            "storageLocation": self.storageLocation,
            "archivedAt": self.archivedAt.isoformat() if self.archivedAt else None,
            "memoryType": self.memoryType,
            "subject": self.subject,
            "tags": self.tags,
            "source": self.source,
            "confidence": self.confidence,
            "validUntil": self.validUntil.isoformat() if self.validUntil else None,
            "supersedes": self.supersedes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "IndexEntry":
        timestamps = Timestamps.from_dict(data["timestamps"]) if data.get("timestamps") else None
        valid_until = data.get("validUntil") or data.get("valid_until")
        return cls(
            entryId=data["entryId"],
            layer=data["layer"],
            projectId=data.get("projectId"),
            title=data["title"],
            timestamps=timestamps,
            contentDigest=data.get("contentDigest"),
            storageLocation=data["storageLocation"],
            archivedAt=datetime.fromisoformat(data["archivedAt"]) if data.get("archivedAt") else None,
            memoryType=data.get("memoryType", "note"),
            subject=data.get("subject"),
            tags=data.get("tags", []),
            source=data.get("source"),
            confidence=data.get("confidence", "confirmed"),
            validUntil=datetime.fromisoformat(valid_until) if valid_until else None,
            supersedes=data.get("supersedes", []),
        )

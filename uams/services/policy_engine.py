"""Pure routing, normalization, digest, and scope-deduplication policy."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from uams.models.memory_entry import MemoryEntry, MemoryLayer, MemoryStatus
from uams.utils.path_normalization import compute_content_digest


class PolicyError(ValueError):
    """Raised when a memory request violates layer invariants."""


@dataclass(frozen=True)
class PolicyDecision:
    layer: MemoryLayer
    projectId: Optional[str]
    title: str
    body: str
    contentDigest: str
    status: MemoryStatus

    @property
    def target_layer(self) -> str:
        return self.layer.value

    @property
    def targetLayer(self) -> str:
        return self.layer.value


class PolicyEngine:
    """Apply one identical memory policy for every AI identity."""

    def __init__(self, project_registry=None):
        self.project_registry = project_registry

    @staticmethod
    def normalize_content(content: str) -> str:
        if content is None:
            raise PolicyError("memory body is required")
        # NFC makes equivalent Unicode representations identical; normalize
        # line endings so Windows and Unix clients share one digest.
        return unicodedata.normalize("NFC", str(content)).replace("\r\n", "\n").replace("\r", "\n")

    normalize_body = normalize_content

    @staticmethod
    def normalize_title(title: str) -> str:
        if title is None:
            return ""
        return unicodedata.normalize("NFC", str(title)).strip()

    @classmethod
    def digest(cls, body: str) -> str:
        return compute_content_digest(cls.normalize_content(body))

    compute_digest = digest
    content_digest = digest

    @staticmethod
    def _status(status) -> MemoryStatus:
        if isinstance(status, MemoryStatus):
            return status
        if status is None:
            return MemoryStatus.ACTIVE
        try:
            return MemoryStatus(str(status).lower())
        except ValueError as exc:
            raise PolicyError(f"unsupported memory status: {status}") from exc

    @staticmethod
    def _layer(layer) -> MemoryLayer:
        if isinstance(layer, MemoryLayer):
            return layer
        try:
            return MemoryLayer(str(layer))
        except ValueError as exc:
            raise PolicyError(f"unsupported memory layer: {layer}") from exc

    def select_layer(self, project_id: Optional[str] = None, status=None, **kwargs) -> MemoryLayer:
        """Select one of the three logical layers from association and status."""
        project_id = project_id or kwargs.get("projectId")
        selected_status = self._status(status)
        if project_id is None:
            if selected_status == MemoryStatus.ARCHIVED:
                raise PolicyError("archived entries require a registered project")
            return MemoryLayer.GLOBAL
        return (
            MemoryLayer.PROJECT_ARCHIVE
            if selected_status == MemoryStatus.ARCHIVED
            else MemoryLayer.PROJECT_ACTIVE
        )

    route = select_layer
    select_target_layer = select_layer

    def decide(
        self,
        title: str,
        body: str,
        project_id: Optional[str] = None,
        status=None,
        layer=None,
        **kwargs,
    ) -> PolicyDecision:
        project_id = project_id or kwargs.get("projectId")
        selected_status = self._status(status)
        selected_layer = self.select_layer(project_id, selected_status)
        if layer is not None and self._layer(layer) != selected_layer:
            raise PolicyError("requested layer is inconsistent with project association and status")
        if selected_layer == MemoryLayer.GLOBAL:
            project_id = None
        normalized_title = self.normalize_title(title)
        normalized_body = self.normalize_content(body)
        return PolicyDecision(
            layer=selected_layer,
            projectId=project_id,
            title=normalized_title,
            body=normalized_body,
            contentDigest=self.digest(normalized_body),
            status=selected_status,
        )

    evaluate = decide

    def prepare_entry(
        self,
        title: str,
        body: str,
        project_id: Optional[str] = None,
        status=None,
        entry_id: Optional[str] = None,
        created_at: Optional[datetime] = None,
        **kwargs,
    ) -> MemoryEntry:
        decision = self.decide(title, body, project_id, status, **kwargs)
        return MemoryEntry(
            entryId=entry_id or MemoryEntry().entryId,
            layer=decision.layer,
            projectId=decision.projectId,
            title=decision.title,
            body=decision.body,
            status=decision.status,
            createdAt=created_at or datetime.now(timezone.utc),
            updatedAt=datetime.now(timezone.utc),
            contentDigest=decision.contentDigest,
        )

    create_entry = prepare_entry

    def find_duplicate(self, store, decision: PolicyDecision) -> Optional[MemoryEntry]:
        """Find a digest match only within the target layer/project scope."""
        for entry in store.list_entries(decision.layer, decision.projectId):
            if entry.contentDigest == decision.contentDigest:
                return entry
        return None

    deduplicate = find_duplicate

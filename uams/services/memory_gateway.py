"""UAMS 记忆的唯一授权读写、治理与精确检索边界。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from uams import SUPPORTED_AI_IDENTITIES
from uams.audit import AuditLogWriter
from uams.models.memory_entry import MemoryEntry, MemoryLayer, MemoryStatus
from uams.services.current_index import CurrentIndex, IndexDataError
from uams.services.memory_store import EntryNotFound, MemoryStore
from uams.services.policy_engine import PolicyEngine
from uams.services.project_registry import ProjectConflict, ProjectNotFound, ProjectRegistry
from uams.services.search_index import SearchIndex, SearchIndexDataError, primary_terms, search_terms
from uams.services.write_source_state import WriteSourceStateManager


class MemoryGatewayError(RuntimeError):
    """统一 Gateway 拒绝。"""


class UnsupportedAIIdentity(MemoryGatewayError):
    """调用方未注册为支持的 AI。"""


class HistoricalSnapshotWriteRejected(MemoryGatewayError):
    """历史快照只读。"""

    def __init__(self, target_layer: Optional[str], project_id: Optional[str]):
        self.targetLayer = self.target_layer = target_layer
        self.projectId = self.project_id = project_id
        guidance = "write new memory through the UAMS gateway"
        if target_layer:
            guidance += f" to {target_layer}"
        if project_id:
            guidance += f" for project {project_id}"
        self.guidance = guidance
        super().__init__(f"historical-snapshot is read-only; {guidance}")


@dataclass
class AccessRequest:
    aiIdentity: str
    operation: str
    scope: str = "global"
    workspacePath: Optional[str] = None
    projectPath: Optional[str] = None
    projectId: Optional[str] = None
    archiveQuery: Optional[Any] = None
    entryPayload: Optional[dict] = None


@dataclass
class AccessDecision:
    outcome: str
    resolvedProjectId: Optional[str] = None
    targetLayer: Optional[str] = None
    entryId: Optional[str] = None
    reason: Optional[str] = None
    auditEventId: Optional[str] = None
    entry: Optional[MemoryEntry] = None
    entries: list[MemoryEntry] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return self.outcome in {"accepted", "duplicate", "read"}

    @property
    def is_duplicate(self) -> bool:
        return self.outcome == "duplicate"

    @property
    def project_id(self) -> Optional[str]:
        return self.resolvedProjectId

    @property
    def target_layer(self) -> Optional[str]:
        return self.targetLayer

    def __getattr__(self, name: str):
        entry = self.__dict__.get("entry")
        if entry is not None and hasattr(entry, name):
            return getattr(entry, name)
        raise AttributeError(name)


class MemoryGateway:
    """执行身份、迁移验收、项目路由、可见性、写入治理与受控检索。"""

    _METADATA_FIELDS = ("memoryType", "subject", "tags", "source", "confidence", "validUntil", "supersedes")
    _ALLOWED_MEMORY_TYPES = frozenset({
        "note", "decision", "architecture", "hardware", "protocol", "bug",
        "build", "deployment", "task", "preference", "audit",
    })
    _ALLOWED_CONFIDENCE = frozenset({"confirmed", "tentative"})

    def __init__(
        self,
        uams_root: str | Path,
        project_registry: Optional[ProjectRegistry] = None,
        write_source_state_manager: Optional[WriteSourceStateManager] = None,
        policy_engine: Optional[PolicyEngine] = None,
        memory_store: Optional[MemoryStore] = None,
        supported_ai: Optional[set[str] | list[str]] = None,
        legacy_source_adapter=None,
        **kwargs,
    ):
        self._uams_root = Path(uams_root).resolve()
        self.store = memory_store or MemoryStore(self._uams_root)
        self.project_registry = project_registry or ProjectRegistry(self._uams_root)
        self.policy = policy_engine or PolicyEngine(self.project_registry)
        self.write_source = write_source_state_manager or WriteSourceStateManager(str(self._uams_root))
        self.legacy_source_adapter = legacy_source_adapter
        self.supported_ai = {str(item).lower() for item in (supported_ai or SUPPORTED_AI_IDENTITIES)}
        self._audit = AuditLogWriter(self._uams_root)

    @property
    def uams_root(self) -> Path:
        return self._uams_root

    @property
    def memory_store(self) -> MemoryStore:
        return self.store

    @property
    def policy_engine(self) -> PolicyEngine:
        return self.policy

    def write(
        self,
        ai_identity: Optional[str] = None,
        title: Optional[str] = None,
        body: Optional[str] = None,
        project_id: Optional[str] = None,
        project_path: Optional[str] = None,
        workspace_path: Optional[str] = None,
        status: Any = MemoryStatus.ACTIVE,
        scope: str = "global",
        operation: str = "write",
        entry: Optional[MemoryEntry] = None,
        request: Optional[AccessRequest] = None,
        **kwargs,
    ) -> AccessDecision:
        request = self._coerce_request(request, kwargs, ai_identity, operation, scope, project_path, workspace_path, project_id)
        self._require_identity(request.aiIdentity)
        self.write_source.require_uams_authority()
        resolved_project = self._resolve_project(request, allow_global=True)
        selected_project_id = resolved_project.projectId if resolved_project else None
        selected_status = status
        metadata = self._metadata_from_payload(request.entryPayload)

        if request.entryPayload:
            title = request.entryPayload.get("title", title)
            body = request.entryPayload.get("body", body)
            selected_status = request.entryPayload.get("status", selected_status)
            if request.entryPayload.get("layer") == MemoryLayer.PROJECT_ARCHIVE.value:
                selected_status = MemoryStatus.ARCHIVED
        if entry is not None:
            title, body, selected_status, selected_project_id = entry.title, entry.body, entry.status, entry.projectId
            metadata = self._metadata_from_entry(entry)
        if request.operation.lower() in {"historical-snapshot", "historical_snapshot", "snapshot"} or request.scope == "historical-snapshot":
            decision = self.policy.decide(title or "", body or "", selected_project_id, selected_status)
            raise HistoricalSnapshotWriteRejected(decision.target_layer, selected_project_id)
        if request.operation.lower() in {"archive", "archive-entry", "archive_entry"}:
            if not request.entryPayload or not request.entryPayload.get("entryId"):
                raise MemoryGatewayError("archive operation requires entryId")
            archived = self.store.archive_entry(request.entryPayload["entryId"], selected_project_id)
            return AccessDecision("accepted", selected_project_id, archived.layer.value, archived.entryId, entry=archived)
        if title is None or body is None:
            raise MemoryGatewayError("write requires title and body")

        self._validate_write_payload(title, body, metadata)
        decision = self.policy.decide(title, body, selected_project_id, selected_status)
        self._validate_supersedes(metadata.get("supersedes", []), decision.projectId)
        duplicate = self.policy.find_duplicate(self.store, decision)
        if duplicate is not None:
            return AccessDecision("duplicate", selected_project_id, decision.target_layer, duplicate.entryId, entry=duplicate)
        self._validate_subject_update(metadata, decision)

        if entry is not None:
            normalized = MemoryEntry(
                schemaVersion=entry.schemaVersion,
                entryId=entry.entryId,
                layer=decision.layer,
                projectId=decision.projectId,
                title=decision.title,
                body=decision.body,
                status=decision.status,
                createdAt=entry.createdAt,
                updatedAt=datetime.now(timezone.utc),
                contentDigest=decision.contentDigest,
                **metadata,
            )
        else:
            normalized = self.policy.prepare_entry(decision.title, decision.body, selected_project_id, decision.status)
            for field_name, value in metadata.items():
                setattr(normalized, field_name, value)
            normalized.__post_init__()
        self.store.save_entry(normalized)
        return AccessDecision("accepted", selected_project_id, normalized.layer.value, normalized.entryId, entry=normalized)

    write_memory = write
    write_entry = write

    def read(
        self,
        ai_identity: Optional[str] = None,
        scope: str = "global",
        project_id: Optional[str] = None,
        project_path: Optional[str] = None,
        workspace_path: Optional[str] = None,
        archive_query: Any = None,
        relative_path: Optional[str] = None,
        request: Optional[AccessRequest] = None,
        **kwargs,
    ) -> list[MemoryEntry] | list[Any] | bytes:
        request = self._coerce_request(request, kwargs, ai_identity, "read", scope, project_path, workspace_path, project_id)
        self._require_identity(request.aiIdentity)
        normalized_scope = request.scope.lower().replace("_", "-")
        if normalized_scope == "historical-snapshot":
            if self.legacy_source_adapter is None:
                raise MemoryGatewayError("historical snapshot adapter is not configured")
            if relative_path or kwargs.get("relativePath"):
                return self.legacy_source_adapter.read_file(relative_path or kwargs["relativePath"])
            return list(self.legacy_source_adapter.enumerate_files())
        resolved_project = self._resolve_project(request, allow_global=normalized_scope == "global")
        selected_project_id = resolved_project.projectId if resolved_project else None
        if normalized_scope == "global":
            return self._read_current(MemoryLayer.GLOBAL, None)
        if normalized_scope in {"project-active", "project", "default"}:
            if selected_project_id is None:
                raise MemoryGatewayError("project-active reads require a registered project")
            return self._read_current(MemoryLayer.GLOBAL, None) + self._read_current(MemoryLayer.PROJECT_ACTIVE, selected_project_id)
        if normalized_scope in {"project-archive", "archive"}:
            if selected_project_id is None:
                raise MemoryGatewayError("archive reads require a registered project")
            return self._read_archive(selected_project_id, request.archiveQuery)
        raise MemoryGatewayError(f"unsupported read scope: {request.scope}")

    read_memory = read
    read_entries = read

    def search(
        self,
        ai_identity: Optional[str] = None,
        query: str = "",
        scope: str = "global",
        project_id: Optional[str] = None,
        project_path: Optional[str] = None,
        workspace_path: Optional[str] = None,
        limit: int = 8,
        memory_type: Optional[str] = None,
        subject: Optional[str] = None,
        tags: Optional[list[str] | tuple[str, ...] | set[str] | str] = None,
        source: Optional[str] = None,
        confidence: Optional[str] = None,
        **kwargs,
    ) -> list[MemoryEntry]:
        if not str(query).strip():
            raise MemoryGatewayError("search query is required")
        request = self._coerce_request(None, kwargs, ai_identity, "search", scope, project_path, workspace_path, project_id)
        self._require_identity(request.aiIdentity)
        normalized_scope = request.scope.lower().replace("_", "-")
        if normalized_scope not in {"global", "project-active", "project", "default"}:
            raise MemoryGatewayError("active memory search supports global or project-active scopes only")
        resolved_project = self._resolve_project(request, allow_global=normalized_scope == "global")
        selected_project_id = resolved_project.projectId if resolved_project else None
        memory_type = memory_type or kwargs.get("memoryType")
        subject = subject or kwargs.get("subject")
        source = source or kwargs.get("source")
        confidence = confidence or kwargs.get("confidence")
        tags = tags if tags is not None else kwargs.get("tag", kwargs.get("tags"))
        index_entries = self._searchable_index_entries(normalized_scope, selected_project_id)
        filtered_index_entries = [
            item for item in self._visible_index_entries(index_entries)
            if self._index_matches_filters(item, memory_type, subject, tags, source, confidence)
        ]
        allowed_ids = {item.entryId for item in filtered_index_entries}
        try:
            candidates = SearchIndex(self._uams_root).candidates(str(query), allowed_ids)
        except SearchIndexDataError:
            self.store.check_health(repair=True)
            candidates = SearchIndex(self._uams_root).candidates(str(query), allowed_ids)
        if not candidates:
            return []
        loaded: list[MemoryEntry] = []
        for item in filtered_index_entries:
            if item.entryId not in candidates:
                continue
            try:
                loaded.append(self.store.load_entry(item.entryId, MemoryLayer(item.layer), item.projectId))
            except EntryNotFound:
                # A crash may have completed a file mutation but not its index;
                # repair once and let the next query use the authoritative view.
                self.store.check_health(repair=True)
        visible = [
            entry for entry in self._visible_entries(loaded)
            if self._entry_matches_filters(entry, memory_type, subject, tags, source, confidence)
        ]
        ranked = [(self._search_score(entry, str(query)), entry) for entry in visible]
        ranked = [(score, entry) for score, entry in ranked if score > 0]
        ranked.sort(key=lambda item: (item[0], item[1].updatedAt), reverse=True)
        return [entry for _, entry in ranked[: max(1, limit)]]

    search_memory = search

    def archive(self, ai_identity: str, entry_id: str, project_id: Optional[str] = None, project_path: Optional[str] = None, workspace_path: Optional[str] = None) -> AccessDecision:
        return self.write(
            ai_identity=ai_identity,
            operation="archive",
            project_id=project_id,
            project_path=project_path,
            workspace_path=workspace_path,
            entryPayload={"entryId": entry_id},
        )

    archive_entry = archive

    def health(self, ai_identity: str, repair: bool = False) -> dict[str, Any]:
        """Return UAMS derived-index health; repair only rebuilds projections."""
        self._require_identity(ai_identity)
        return self.store.check_health(repair=repair)

    def _read_current(self, layer: MemoryLayer, project_id: Optional[str]) -> list[MemoryEntry]:
        try:
            index_entries = CurrentIndex(self._uams_root).find(layer, project_id)
        except IndexDataError:
            self.store.check_health(repair=True)
            index_entries = CurrentIndex(self._uams_root).find(layer, project_id)
        entries: list[MemoryEntry] = []
        for item in index_entries:
            try:
                entries.append(self.store.load_entry(item.entryId, layer, project_id))
            except EntryNotFound:
                self.store.check_health(repair=True)
        return self._visible_entries(entries)

    def _read_archive(self, project_id: str, query: Any) -> list[MemoryEntry]:
        from uams.services.archive_reader import ArchiveReader
        try:
            return ArchiveReader(self.store).read(project_id, query)
        except ValueError as exc:
            raise MemoryGatewayError(str(exc)) from exc

    def _searchable_index_entries(self, scope: str, project_id: Optional[str]):
        try:
            index = CurrentIndex(self._uams_root)
            if scope == "global":
                return index.find(MemoryLayer.GLOBAL, None)
            return index.find(MemoryLayer.GLOBAL, None) + index.find(MemoryLayer.PROJECT_ACTIVE, project_id)
        except IndexDataError:
            self.store.check_health(repair=True)
            return self._searchable_index_entries(scope, project_id)

    @staticmethod
    def _visible_entries(entries: list[MemoryEntry]) -> list[MemoryEntry]:
        now = datetime.now(timezone.utc)
        eligible = [
            entry for entry in entries
            if entry.status == MemoryStatus.ACTIVE and (entry.validUntil is None or entry.validUntil >= now)
        ]
        superseded_ids = {entry_id for entry in eligible for entry_id in entry.supersedes}
        return [entry for entry in eligible if entry.entryId not in superseded_ids]

    @staticmethod
    def _visible_index_entries(entries):
        now = datetime.now(timezone.utc)
        eligible = [entry for entry in entries if entry.validUntil is None or entry.validUntil >= now]
        superseded_ids = {entry_id for entry in eligible for entry_id in entry.supersedes}
        return [entry for entry in eligible if entry.entryId not in superseded_ids]

    @staticmethod
    def _normalize_tags(tags: Optional[list[str] | tuple[str, ...] | set[str] | str]) -> set[str]:
        if tags is None:
            return set()
        values = [tags] if isinstance(tags, str) else tags
        return {str(tag).strip().casefold() for tag in values if str(tag).strip()}

    def _index_matches_filters(self, entry, memory_type, subject, tags, source, confidence) -> bool:
        normalized_tags = self._normalize_tags(tags)
        if memory_type and entry.memoryType.casefold() != str(memory_type).casefold():
            return False
        if subject and str(subject).casefold() not in (entry.subject or "").casefold():
            return False
        if normalized_tags and not normalized_tags.issubset({tag.casefold() for tag in entry.tags}):
            return False
        if source and str(source).casefold() not in (entry.source or "").casefold():
            return False
        if confidence and entry.confidence.casefold() != str(confidence).casefold():
            return False
        return True

    def _entry_matches_filters(self, entry: MemoryEntry, memory_type, subject, tags, source, confidence) -> bool:
        return self._index_matches_filters(entry, memory_type, subject, tags, source, confidence)

    def _search_score(self, entry: MemoryEntry, query: str) -> int:
        terms = primary_terms(query)
        query_tokens = search_terms(query)
        if not terms or not query_tokens:
            return 0
        fields = (
            (16, " ".join((entry.title, entry.subject or "", entry.memoryType, " ".join(entry.tags))).casefold()),
            (6, (entry.source or "").casefold()),
            (4, entry.body.casefold()),
        )
        matched_primary: set[str] = set()
        score = 0
        for weight, value in fields:
            field_tokens = search_terms(value)
            score += weight * len(query_tokens & field_tokens)
            for term in terms:
                term_tokens = search_terms(term)
                if term in value or (
                    term_tokens and len(term_tokens & field_tokens) >= max(1, (len(term_tokens) * 2 + 2) // 3)
                ):
                    matched_primary.add(term)
                    score += weight * 3
            if query.casefold().strip() in value:
                score += weight * 20
        required = 1 if len(terms) == 1 else max(2, (len(terms) + 1) // 2)
        return score if len(matched_primary) >= required else 0

    def _validate_write_payload(self, title: str, body: str, metadata: dict[str, Any]) -> None:
        if not str(title).strip() or not str(body).strip():
            raise MemoryGatewayError("title and body must not be blank")
        if self._contains_sensitive_material(str(body)):
            raise MemoryGatewayError("memory body appears to contain a credential or private key")
        memory_type = str(metadata.get("memoryType", "note")).strip().casefold()
        confidence = str(metadata.get("confidence", "confirmed")).strip().casefold()
        metadata["memoryType"] = memory_type
        metadata["confidence"] = confidence
        if memory_type not in self._ALLOWED_MEMORY_TYPES:
            raise MemoryGatewayError(f"unsupported memoryType: {memory_type}")
        if confidence not in self._ALLOWED_CONFIDENCE:
            raise MemoryGatewayError(f"unsupported confidence: {confidence}")
        if confidence == "confirmed" and not str(metadata.get("source") or "").strip():
            raise MemoryGatewayError("confirmed memory requires a non-empty source")
        if memory_type != "note" and not str(metadata.get("subject") or "").strip():
            raise MemoryGatewayError(f"{memory_type} memory requires a stable subject")

    @staticmethod
    def _contains_sensitive_material(value: str) -> bool:
        normalized = value.casefold()
        credential_markers = ("-----begin private key-----", "aws_secret_access_key", "authorization: bearer ")
        if any(marker in normalized for marker in credential_markers):
            return True
        import re

        return bool(re.search(r"(?:api[_-]?key|password|secret|access[_-]?token)\s*[:=]\s*['\"]?[^\s'\"]{8,}", value, flags=re.IGNORECASE))

    def _validate_subject_update(self, metadata: dict[str, Any], decision) -> None:
        subject = str(metadata.get("subject") or "").strip().casefold()
        if not subject:
            return
        memory_type = str(metadata.get("memoryType", "note")).casefold()
        visible = self._visible_entries(self.store.list_entries(decision.layer, decision.projectId))
        predecessors = [
            entry for entry in visible
            if entry.memoryType.casefold() == memory_type and (entry.subject or "").casefold() == subject
        ]
        missing = [entry.entryId for entry in predecessors if entry.entryId not in set(metadata.get("supersedes", []))]
        if missing:
            raise MemoryGatewayError(
                "a current memory already exists for this type and subject; pass --supersedes for: " + ", ".join(missing)
            )

    def _validate_supersedes(self, entry_ids: list[str], project_id: Optional[str]) -> None:
        for entry_id in entry_ids:
            try:
                predecessor = self.store.load_entry(entry_id)
            except EntryNotFound as exc:
                raise MemoryGatewayError(f"supersedes entry does not exist: {entry_id}") from exc
            if predecessor.projectId != project_id:
                raise MemoryGatewayError("supersedes entries must remain in the same project scope")
            expected_layer = MemoryLayer.GLOBAL if project_id is None else MemoryLayer.PROJECT_ACTIVE
            if predecessor.layer != expected_layer or predecessor.status != MemoryStatus.ACTIVE:
                raise MemoryGatewayError("supersedes entries must reference active entries in the same scope")

    def _metadata_from_payload(self, payload: Optional[dict]) -> dict[str, Any]:
        if not payload:
            return {}
        metadata: dict[str, Any] = {}
        aliases = {"memoryType": "memory_type", "validUntil": "valid_until"}
        for field_name in self._METADATA_FIELDS:
            value = payload.get(field_name, payload.get(aliases.get(field_name, "")))
            if value is None:
                continue
            if field_name in {"tags", "supersedes"}:
                value = [value] if isinstance(value, str) else list(value)
            if field_name == "validUntil" and isinstance(value, str):
                try:
                    value = datetime.fromisoformat(value)
                except ValueError as exc:
                    raise MemoryGatewayError("validUntil must be an ISO-8601 datetime") from exc
            metadata[field_name] = value
        return metadata

    def _metadata_from_entry(self, entry: MemoryEntry) -> dict[str, Any]:
        return {field_name: getattr(entry, field_name) for field_name in self._METADATA_FIELDS}

    def _resolve_project(self, request: AccessRequest, allow_global: bool):
        if request.projectId:
            try:
                return self.project_registry.get(request.projectId)
            except ProjectNotFound:
                self._reject(request, f"unregistered project id: {request.projectId}")
                raise
        if request.projectPath or request.workspacePath:
            try:
                return self.project_registry.resolve(request.projectPath, request.workspacePath)
            except (ProjectNotFound, ProjectConflict) as exc:
                self._reject(request, str(exc))
                raise
        if not allow_global and request.scope != "global":
            raise MemoryGatewayError("project context is required")
        return None

    def _require_identity(self, identity: Optional[str]) -> str:
        normalized = str(identity or "").strip().lower()
        if normalized not in self.supported_ai:
            self._reject_raw(identity, "unsupported AI identity")
            raise UnsupportedAIIdentity(f"unsupported AI identity: {identity}")
        return normalized

    @staticmethod
    def _coerce_request(request, kwargs, ai_identity, operation, scope, project_path, workspace_path, project_id) -> AccessRequest:
        if request is not None:
            return request
        payload = kwargs.get("entryPayload") or kwargs.get("entry_payload")
        return AccessRequest(
            aiIdentity=ai_identity or kwargs.get("aiIdentity") or kwargs.get("ai_identity") or "",
            operation=operation or kwargs.get("operation") or "read",
            scope=scope or kwargs.get("scope") or "global",
            workspacePath=workspace_path or kwargs.get("workspacePath") or kwargs.get("workspace_path"),
            projectPath=project_path or kwargs.get("projectPath") or kwargs.get("project_path"),
            projectId=project_id or kwargs.get("projectId") or kwargs.get("project_id"),
            archiveQuery=kwargs.get("archiveQuery") or kwargs.get("archive_query"),
            entryPayload=payload,
        )

    def _reject(self, request: AccessRequest, reason: str) -> str:
        return self._reject_raw(request.aiIdentity, reason, request.operation, request.projectPath or request.workspacePath)

    def _reject_raw(self, identity, reason: str, operation: str = "unknown", requested_path=None) -> str:
        return self._audit.access_rejection({
            "eventType": "access_rejected",
            "aiIdentity": identity,
            "operation": operation,
            "requestedPath": requested_path,
            "reason": reason,
        })

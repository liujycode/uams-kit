"""Public service interfaces for UAMS migration and memory operations."""

from uams.services.archive_catalog import ArchiveCatalog
from uams.services.archive_reader import ArchiveReader
from uams.services.current_index import CurrentIndex, IndexDataError
from uams.services.index_consistency import IndexConsistencyManager
from uams.services.memory_gateway import (
    AccessDecision,
    AccessRequest,
    HistoricalSnapshotWriteRejected,
    MemoryGateway,
    MemoryGatewayError,
    UnsupportedAIIdentity,
)
from uams.utils.interprocess_lock import InterProcessFileLock, LockAcquisitionError
from uams.services.search_index import SearchIndex, SearchIndexDataError
from uams.services.memory_store import EntryNotFound, MemoryStore, MemoryStoreError
from uams.services.migration_acceptance import AcceptanceRecordStore, MigrationAcceptanceStore
from uams.services.migration_copy import MigrationCopyService
from uams.services.migration_validation import MigrationValidationService
from uams.services.policy_engine import PolicyDecision, PolicyEngine, PolicyError
from uams.services.project_registry import (
    ProjectConflict,
    ProjectNotFound,
    ProjectRegistry,
    ProjectRegistryError,
    ProjectResolutionError,
)
from uams.services.source_discovery import SourceDiscoveryService
from uams.services.source_preservation import (
    SourcePreservationChecker,
    SourcePreservationDifference,
    SourcePreservationReport,
    SourcePreservationService,
)
from uams.services.write_source_state import (
    WriteSourceError,
    WriteSourceManager,
    WriteSourceNotAccepted,
    WriteSourceState,
    WriteSourceStateManager,
    WriteSourceTransitionRejected,
)

__all__ = [
    "SourceDiscoveryService", "MigrationCopyService", "MigrationValidationService",
    "SourcePreservationService", "SourcePreservationChecker", "SourcePreservationReport",
    "SourcePreservationDifference", "MigrationAcceptanceStore", "AcceptanceRecordStore",
    "WriteSourceStateManager", "WriteSourceManager", "WriteSourceState", "WriteSourceError",
    "WriteSourceTransitionRejected", "WriteSourceNotAccepted", "MemoryStore", "MemoryStoreError",
    "EntryNotFound", "InterProcessFileLock", "LockAcquisitionError", "SearchIndex", "SearchIndexDataError",
    "CurrentIndex", "ArchiveCatalog", "ArchiveReader", "IndexConsistencyManager",
    "IndexDataError", "PolicyEngine", "PolicyDecision", "PolicyError", "ProjectRegistry",
    "ProjectRegistryError", "ProjectNotFound", "ProjectConflict", "ProjectResolutionError",
    "MemoryGateway", "MemoryGatewayError", "UnsupportedAIIdentity",
    "HistoricalSnapshotWriteRejected", "AccessRequest", "AccessDecision",
]

"""Compatibility exports for the UAMS memory gateway."""
from uams.services.memory_gateway import (
    AccessDecision,
    AccessRequest,
    HistoricalSnapshotWriteRejected,
    MemoryGateway,
    MemoryGatewayError,
    UnsupportedAIIdentity,
)

__all__ = [
    "MemoryGateway", "MemoryGatewayError", "UnsupportedAIIdentity",
    "HistoricalSnapshotWriteRejected", "AccessRequest", "AccessDecision",
]

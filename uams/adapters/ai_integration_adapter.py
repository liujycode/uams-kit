"""AI integration adapters that expose only the UAMS Gateway boundary."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from uams.audit import AuditLogWriter
from uams.services.ai_identity_registry import AIIdentityRegistry
from uams.services.memory_gateway import AccessDecision, MemoryGateway


class AIIntegrationAdapter(ABC):
    """Abstract adapter that forwards all memory operations through Gateway."""

    def __init__(self, gateway: MemoryGateway, identity_registry: AIIdentityRegistry | None = None):
        self._gateway = gateway
        self._registry = identity_registry or AIIdentityRegistry(gateway.uams_root)
        self._audit = AuditLogWriter(gateway.uams_root)

    @property
    @abstractmethod
    def ai_identity(self) -> str:
        """Registered identity presented to the Gateway."""

    def read(self, scope: str = "global", **kwargs):
        return self._gateway.read(ai_identity=self.ai_identity, scope=scope, **kwargs)

    def write(self, title: str, body: str, **kwargs) -> AccessDecision:
        decision = self._gateway.write(ai_identity=self.ai_identity, title=title, body=body, **kwargs)
        self._audit.policy_decision({
            "aiIdentity": self.ai_identity,
            "operation": "write",
            "outcome": decision.outcome,
            "targetLayer": decision.targetLayer,
            "projectId": decision.resolvedProjectId,
            "entryId": decision.entryId,
        })
        return decision

    def search(self, query: str, scope: str = "global", **kwargs):
        return self._gateway.search(ai_identity=self.ai_identity, query=query, scope=scope, **kwargs)

    search_memory = search

    def archive(self, entry_id: str, **kwargs) -> AccessDecision:
        decision = self._gateway.archive(ai_identity=self.ai_identity, entry_id=entry_id, **kwargs)
        self._audit.policy_decision({
            "aiIdentity": self.ai_identity,
            "operation": "archive",
            "outcome": decision.outcome,
            "targetLayer": decision.targetLayer,
            "projectId": decision.resolvedProjectId,
            "entryId": decision.entryId,
        })
        return decision

    def health(self, repair: bool = False):
        """Check or rebuild derived UAMS indexes through the Gateway."""
        return self._gateway.health(ai_identity=self.ai_identity, repair=repair)

    def historical_snapshot(self, relative_path: str | None = None):
        kwargs: dict[str, Any] = {}
        if relative_path is not None:
            kwargs["relative_path"] = relative_path
        return self.read(scope="historical-snapshot", **kwargs)


class RegisteredAIIntegrationAdapter(AIIntegrationAdapter):
    """Concrete adapter for a built-in or registered future AI identity."""

    def __init__(self, gateway: MemoryGateway, ai_identity: str, identity_registry: AIIdentityRegistry | None = None):
        super().__init__(gateway, identity_registry)
        self._ai_identity = self._registry.normalize(ai_identity)
        if not self._registry.is_supported(self._ai_identity):
            raise ValueError(f"AI identity is not registered: {ai_identity}")
        # Gateway remains the only persistence boundary. The adapter merely
        # supplies a registry-authorized integration identity to that boundary.
        self._gateway.supported_ai.add(self._ai_identity)

    @property
    def ai_identity(self) -> str:
        return self._ai_identity

"""Adapters for protected source and AI integration access."""

from uams.adapters.ai_integration_adapter import AIIntegrationAdapter, RegisteredAIIntegrationAdapter
from uams.adapters.legacy_source_adapter import LegacySourceAdapter

__all__ = ["AIIntegrationAdapter", "RegisteredAIIntegrationAdapter", "LegacySourceAdapter"]

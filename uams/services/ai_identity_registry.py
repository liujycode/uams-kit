"""Persistent registry for UAMS AI integrations."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from uams import SUPPORTED_AI_IDENTITIES


class AIIdentityRegistryError(ValueError):
    """Raised when an AI integration identity is invalid."""


class AIIdentityRegistry:
    """Resolve built-in and explicitly registered future AI identities."""

    def __init__(self, uams_root: str | os.PathLike[str]):
        self._root = Path(uams_root).resolve()
        self._path = self._root / "registry" / "ai-integrations.json"
        self._built_in = {self.normalize(identity) for identity in SUPPORTED_AI_IDENTITIES}

    @property
    def path(self) -> Path:
        return self._path

    @staticmethod
    def normalize(identity: str) -> str:
        normalized = str(identity or "").strip().lower()
        if not normalized:
            raise AIIdentityRegistryError("AI identity must not be empty")
        return normalized

    def identities(self) -> set[str]:
        return self._built_in | set(self._load_registered())

    def is_supported(self, identity: str) -> bool:
        try:
            return self.normalize(identity) in self.identities()
        except AIIdentityRegistryError:
            return False

    def register(self, identity: str) -> str:
        normalized = self.normalize(identity)
        registered = self._load_registered()
        if normalized not in registered:
            registered[normalized] = {"registeredAt": datetime.now(timezone.utc).isoformat()}
            self._write_registered(registered)
        return normalized

    def _load_registered(self) -> dict[str, dict]:
        if not self._path.is_file():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            identities = data.get("identities", {})
            if not isinstance(identities, dict):
                raise TypeError("identities must be an object")
            return {self.normalize(identity): metadata for identity, metadata in identities.items()}
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise AIIdentityRegistryError(f"invalid AI identity registry: {self._path}") from exc

    def _write_registered(self, identities: dict[str, dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=".ai-integrations-", suffix=".tmp", dir=self._path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
                json.dump({"identities": identities}, output, indent=2, ensure_ascii=False, sort_keys=True)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_name, self._path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
            raise

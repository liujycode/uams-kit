"""Migration acceptance-gated authoritative write-source state."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from uams.services.migration_acceptance import MigrationAcceptanceStore


class WriteSourceError(RuntimeError):
    """Base error for an invalid write-source transition or write."""


class WriteSourceTransitionRejected(WriteSourceError):
    """Raised when no successful acceptance record authorizes transition."""


class WriteSourceNotAccepted(WriteSourceError):
    """Raised when a write is attempted before UAMS becomes authoritative."""


@dataclass(frozen=True)
class WriteSourceState:
    """Durable state describing the current authoritative write source."""

    source: str
    manifestId: Optional[str] = None
    transitionedAt: Optional[str] = None

    @property
    def uams_is_authoritative(self) -> bool:
        return self.source == "uams"

    @property
    def is_uams_authoritative(self) -> bool:
        return self.uams_is_authoritative

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "manifestId": self.manifestId,
            "transitionedAt": self.transitionedAt,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WriteSourceState":
        return cls(
            source=data.get("source", "legacy"),
            manifestId=data.get("manifestId"),
            transitionedAt=data.get("transitionedAt"),
        )


class WriteSourceStateManager:
    """Manage the one-way transition from legacy to UAMS writes.

    The manager consults only acceptance records stored under UAMS_ROOT.  It
    never writes to, or uses as a write target, the legacy source.
    """

    STATE_FILE_NAME = "write-source-state.json"
    UAMS_SOURCE = "uams"
    LEGACY_SOURCE = "legacy"

    def __init__(self, uams_root: str) -> None:
        self._uams_root = Path(uams_root).resolve()
        self._state_path = self._uams_root / "migration" / self.STATE_FILE_NAME
        self._audit_path = self._uams_root / "audit" / "migration.jsonl"
        self._acceptances = MigrationAcceptanceStore(str(self._uams_root))

    @property
    def state_path(self) -> Path:
        return self._state_path

    @property
    def acceptance_store(self) -> MigrationAcceptanceStore:
        return self._acceptances

    def get_state(self) -> WriteSourceState:
        if not self._state_path.is_file():
            return WriteSourceState(source=self.LEGACY_SOURCE)
        try:
            with self._state_path.open("r", encoding="utf-8") as source:
                return WriteSourceState.from_dict(json.load(source))
        except (OSError, ValueError, KeyError, TypeError):
            # A malformed state must fail closed rather than authorize writes.
            return WriteSourceState(source=self.LEGACY_SOURCE)

    state = get_state

    def is_uams_authoritative(self) -> bool:
        state = self.get_state()
        return state.uams_is_authoritative and bool(
            state.manifestId and self._acceptances.is_successful(state.manifestId)
        )

    is_authoritative = is_uams_authoritative
    can_write = is_uams_authoritative

    def request_transition(self, manifest_id: Optional[str] = None) -> WriteSourceState:
        """Make UAMS authoritative only when a successful acceptance exists."""
        selected_id = manifest_id
        if selected_id is None:
            successful = self._acceptances.successful_manifest_ids()
            if len(successful) != 1:
                reason = (
                    "exactly one successful migration acceptance is required; "
                    f"found {len(successful)}"
                )
                self._record_rejection(selected_id, reason)
                raise WriteSourceTransitionRejected(reason)
            selected_id = successful[0]

        if not self._acceptances.is_successful(selected_id):
            reason = f"migration acceptance is not successful: {selected_id}"
            self._record_rejection(selected_id, reason)
            raise WriteSourceTransitionRejected(reason)

        state = WriteSourceState(
            source=self.UAMS_SOURCE,
            manifestId=selected_id,
            transitionedAt=datetime.now(timezone.utc).isoformat(),
        )
        self._write_state(state)
        return state

    transition_to_uams = request_transition
    enable_uams = request_transition

    def require_uams_authority(self) -> WriteSourceState:
        """Return state for a write or fail closed before any write occurs."""
        state = self.get_state()
        if not self.is_uams_authoritative():
            raise WriteSourceNotAccepted(
                "UAMS is not the authoritative write source; a successful "
                "migration acceptance record is required"
            )
        return state

    assert_uams_authoritative = require_uams_authority

    def write_target(self, relative_path: str) -> Path:
        """Return a UAMS-local write target after enforcing the acceptance gate."""
        self.require_uams_authority()
        target = (self._uams_root / relative_path).resolve()
        try:
            target.relative_to(self._uams_root)
        except ValueError as exc:
            raise ValueError("write target must remain inside UAMS_ROOT") from exc
        return target

    def _write_state(self, state: WriteSourceState) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=".write-source-state-", suffix=".tmp", dir=self._state_path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump(state.to_dict(), output, indent=2, ensure_ascii=False)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_name, self._state_path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
            raise

    def _record_rejection(self, manifest_id: Optional[str], reason: str) -> None:
        self._audit_path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "eventType": "write_source_transition_rejected",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "manifestId": manifest_id,
            "reason": reason,
        }
        with self._audit_path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(event, ensure_ascii=False) + "\n")


# Concise aliases for integrations and tests.
WriteSourceManager = WriteSourceStateManager

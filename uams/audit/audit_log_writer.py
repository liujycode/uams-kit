"""JSONL audit writers constrained to UAMS_ROOT."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from uams.utils.interprocess_lock import InterProcessFileLock


class AuditLogWriter:
    """Append auditable migration, rejection and policy events under UAMS_ROOT."""

    FILES = {
        "migration": "migration.jsonl",
        "access_rejections": "access-rejections.jsonl",
        "policy_decisions": "policy-decisions.jsonl",
    }

    def __init__(self, uams_root: str | os.PathLike[str]):
        self._root = Path(uams_root).resolve()

    def write(self, category: str, event: dict[str, Any]) -> str:
        try:
            filename = self.FILES[category]
        except KeyError as exc:
            raise ValueError(f"unsupported audit category: {category}") from exc
        event_id = str(event.get("eventId") or f"audit-{uuid.uuid4()}")
        record = {**event, "eventId": event_id, "timestamp": event.get("timestamp") or datetime.now(timezone.utc).isoformat()}
        destination = (self._root / "audit" / filename).resolve()
        try:
            destination.relative_to(self._root)
        except ValueError as exc:
            raise ValueError("audit log must remain under UAMS_ROOT") from exc
        destination.parent.mkdir(parents=True, exist_ok=True)
        with InterProcessFileLock(destination.with_suffix(destination.suffix + ".lock")):
            with destination.open("a", encoding="utf-8", newline="\n") as output:
                output.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                output.flush()
                os.fsync(output.fileno())
        return event_id

    def migration(self, event: dict[str, Any]) -> str:
        return self.write("migration", event)

    def access_rejection(self, event: dict[str, Any]) -> str:
        return self.write("access_rejections", event)

    def policy_decision(self, event: dict[str, Any]) -> str:
        return self.write("policy_decisions", event)

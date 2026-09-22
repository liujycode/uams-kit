"""Persistent inverted index for active UAMS memory retrieval.

The index stores normalized search terms and routing metadata only; canonical
memory bodies remain in their Markdown entries and are opened only for ranked
candidates returned by this index.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from uams.models.memory_entry import MemoryEntry, MemoryLayer


SEARCH_INDEX_SCHEMA_VERSION = 1
_TOKEN_PATTERN = re.compile(r"[a-z0-9_./:-]+|[\u4e00-\u9fff]+", re.IGNORECASE)


class SearchIndexDataError(RuntimeError):
    """Raised when the persisted active-memory search index is invalid."""


def primary_terms(value: str) -> list[str]:
    """Return meaningful user terms without degrading Chinese into single chars."""
    terms: list[str] = []
    for raw in _TOKEN_PATTERN.findall(str(value).casefold()):
        token = raw.strip()
        if not token:
            continue
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            if len(token) >= 2:
                terms.append(token)
        elif len(token) >= 2:
            terms.append(token)
    return list(dict.fromkeys(terms))


def search_terms(value: str) -> set[str]:
    """Expand text to stable terms, including bounded CJK phrase n-grams."""
    terms: set[str] = set()
    for token in _TOKEN_PATTERN.findall(str(value).casefold()):
        token = token.strip()
        if not token:
            continue
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            if len(token) == 1:
                continue
            terms.add(token)
            maximum = min(8, len(token))
            for size in range(2, maximum + 1):
                terms.update(token[offset:offset + size] for offset in range(0, len(token) - size + 1))
        elif len(token) >= 2:
            terms.add(token)
    return terms


class SearchIndex:
    """Atomic inverted index of active entry terms and scope metadata."""

    def __init__(self, uams_root: str | os.PathLike[str]):
        self._path = Path(uams_root).resolve() / "index" / "search.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def payload_for(self, entries: Iterable[MemoryEntry]) -> dict:
        postings: dict[str, set[str]] = defaultdict(set)
        routing: dict[str, dict[str, str | None]] = {}
        for entry in entries:
            if entry.layer == MemoryLayer.PROJECT_ARCHIVE:
                continue
            routing[entry.entryId] = {"layer": entry.layer.value, "projectId": entry.projectId}
            text = "\n".join((
                entry.title,
                entry.subject or "",
                entry.memoryType,
                " ".join(entry.tags),
                entry.source or "",
                entry.body,
            ))
            for term in search_terms(text):
                postings[term].add(entry.entryId)
        return {
            "schemaVersion": SEARCH_INDEX_SCHEMA_VERSION,
            "entries": dict(sorted(routing.items())),
            "postings": {term: sorted(entry_ids) for term, entry_ids in sorted(postings.items())},
        }

    def payload(self) -> dict:
        if not self._path.exists():
            raise SearchIndexDataError(f"missing search index: {self._path}")
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            if payload.get("schemaVersion", 0) != SEARCH_INDEX_SCHEMA_VERSION:
                raise ValueError("unsupported schema version")
            if not isinstance(payload.get("entries"), dict) or not isinstance(payload.get("postings"), dict):
                raise ValueError("invalid search index structure")
            return payload
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise SearchIndexDataError(f"invalid search index: {self._path}") from exc

    def replace(self, entries: Iterable[MemoryEntry]) -> None:
        self._atomic_write(self.payload_for(entries))

    def candidates(self, query: str, allowed_entry_ids: set[str]) -> set[str]:
        payload = self.payload()
        candidates: set[str] = set()
        for term in search_terms(query):
            candidates.update(payload["postings"].get(term, []))
        return candidates & allowed_entry_ids

    def matches(self, entries: Iterable[MemoryEntry]) -> bool:
        return self.payload() == self.payload_for(entries)

    def _atomic_write(self, payload: dict) -> None:
        fd, temporary_name = tempfile.mkstemp(prefix=".search-", suffix=".tmp", dir=self._path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
                json.dump(payload, output, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_name, self._path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
            raise

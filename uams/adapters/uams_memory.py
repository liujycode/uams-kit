#!/usr/bin/env python3
"""Tool-neutral UAMS command-line adapter for registered AI integrations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

DEFAULT_UAMS_ROOT = Path(__file__).resolve().parents[2]
if str(DEFAULT_UAMS_ROOT) not in sys.path:
    sys.path.insert(0, str(DEFAULT_UAMS_ROOT))

from uams import SUPPORTED_AI_IDENTITIES, __version__
from uams.adapters import RegisteredAIIntegrationAdapter
from uams.services import MemoryGateway, ProjectConflict, ProjectNotFound, ProjectRegistry
from uams.services.write_source_state import WriteSourceStateManager


def emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def entry_data(entry: Any) -> dict[str, Any]:
    return entry.to_dict() if hasattr(entry, "to_dict") else dict(entry)


def build_adapter(root: Path, ai_identity: str):
    registry = ProjectRegistry(root)
    write_state = WriteSourceStateManager(str(root))
    gateway = MemoryGateway(root, project_registry=registry, write_source_state_manager=write_state)
    return RegisteredAIIntegrationAdapter(gateway, ai_identity), registry, write_state


def project_context(args: argparse.Namespace) -> dict[str, str]:
    context: dict[str, str] = {}
    if args.project_id:
        context["project_id"] = args.project_id
    if args.project_path:
        context["project_path"] = args.project_path
    if args.workspace_path:
        context["workspace_path"] = args.workspace_path
    return context


def metadata_payload(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "memoryType": args.memory_type,
        "subject": args.subject,
        "tags": args.tag,
        "source": args.source,
        "confidence": args.confidence,
        "validUntil": args.valid_until,
        "supersedes": args.supersedes,
    }


def search_filter_payload(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if args.memory_type:
        payload["memory_type"] = args.memory_type
    if args.subject:
        payload["subject"] = args.subject
    if args.tag:
        payload["tags"] = args.tag
    if args.source:
        payload["source"] = args.source
    if args.confidence:
        payload["confidence"] = args.confidence
    return payload


def command_status(args: argparse.Namespace) -> int:
    _, registry, write_state = build_adapter(args.uams_root, args.ai_identity)
    emit({
        "uamsRoot": str(args.uams_root),
        "uamsVersion": __version__,
        "aiIdentity": args.ai_identity,
        "uamsAuthoritative": write_state.is_uams_authoritative(),
        "registeredProjects": [record.to_dict() for record in registry.list_projects()],
    })
    return 0


def command_discover(args: argparse.Namespace) -> int:
    build_adapter(args.uams_root, args.ai_identity)
    command = f'python "{Path(__file__).resolve()}" --ai-identity <identity>'
    emit({
        "schemaVersion": 1,
        "system": "UAMS",
        "uamsVersion": __version__,
        "canonicalRoot": str(args.uams_root),
        "entryCommand": command,
        "supportedAIIdentities": SUPPORTED_AI_IDENTITIES,
        "discoveryFiles": [
            str(args.uams_root.parent / "UAMS_ENTRY.json"),
            str(args.uams_root.parent / "UAMS_ENTRY.md"),
        ],
        "boundary": "All memory read, search, write and archive operations must use this CLI or MemoryGateway.",
        "commands": ["status", "health", "read", "search", "write", "archive", "register-project"],
    })
    return 0


def command_health(args: argparse.Namespace) -> int:
    adapter, _, _ = build_adapter(args.uams_root, args.ai_identity)
    emit(adapter.health(repair=args.repair))
    return 0


def command_register_project(args: argparse.Namespace) -> int:
    _, registry, _ = build_adapter(args.uams_root, args.ai_identity)
    try:
        existing = registry.resolve(project_path=args.project_path)
    except ProjectNotFound:
        existing = None
    if existing is not None:
        if args.project_id and args.project_id != existing.projectId:
            raise ValueError(f"project path is already registered as {existing.projectId}")
        if args.workspace_alias:
            existing = registry.add_workspace_aliases(existing.projectId, args.workspace_alias)
            emit({"outcome": "aliases-updated", "project": existing.to_dict()})
        else:
            emit({"outcome": "existing", "project": existing.to_dict()})
        return 0
    record = registry.register(args.project_path, workspace_aliases=args.workspace_alias, project_id=args.project_id)
    emit({"outcome": "registered", "project": record.to_dict()})
    return 0


def command_read(args: argparse.Namespace) -> int:
    adapter, _, _ = build_adapter(args.uams_root, args.ai_identity)
    entries = adapter.read(scope=args.scope, archive_query=args.archive_query, **project_context(args))
    if isinstance(entries, bytes):
        sys.stdout.buffer.write(entries)
        return 0
    emit({"scope": args.scope, "entries": [entry_data(entry) for entry in entries]})
    return 0


def command_search(args: argparse.Namespace) -> int:
    adapter, _, _ = build_adapter(args.uams_root, args.ai_identity)
    entries = adapter.search(args.query, scope=args.scope, limit=args.limit, **project_context(args), **search_filter_payload(args))
    emit({"query": args.query, "scope": args.scope, "entries": [entry_data(entry) for entry in entries]})
    return 0


def command_write(args: argparse.Namespace) -> int:
    adapter, _, _ = build_adapter(args.uams_root, args.ai_identity)
    decision = adapter.write(args.title, args.body, entryPayload=metadata_payload(args), **project_context(args))
    emit({
        "outcome": decision.outcome,
        "entryId": decision.entryId,
        "targetLayer": decision.targetLayer,
        "resolvedProjectId": decision.resolvedProjectId,
        "entry": entry_data(decision.entry) if decision.entry else None,
    })
    return 0


def command_archive(args: argparse.Namespace) -> int:
    adapter, _, _ = build_adapter(args.uams_root, args.ai_identity)
    decision = adapter.archive(args.entry_id, **project_context(args))
    emit({"outcome": decision.outcome, "entryId": decision.entryId, "targetLayer": decision.targetLayer, "resolvedProjectId": decision.resolvedProjectId})
    return 0


def add_project_options(parser: argparse.ArgumentParser, required: bool = False) -> None:
    parser.add_argument("--project-id", required=required, help="Registered UAMS project ID")
    parser.add_argument("--project-path", help="Registered project root path")
    parser.add_argument("--workspace-path", help="Registered workspace alias path")


def add_search_filter_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--type", dest="memory_type", help="Exact memory type")
    parser.add_argument("--subject", help="Subject filter")
    parser.add_argument("--tag", action="append", default=[], help="Repeatable; all supplied tags must match")
    parser.add_argument("--source", help="Source filter")
    parser.add_argument("--confidence", choices=("confirmed", "tentative"), help="Confidence filter")


def add_metadata_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--type", dest="memory_type", default="note", help="note, decision, architecture, hardware, protocol, bug, build, deployment, task, preference or audit")
    parser.add_argument("--subject", help="Stable topic or entity; required for non-note types")
    parser.add_argument("--tag", action="append", default=[], help="Repeatable retrieval tag")
    parser.add_argument("--source", help="Evidence source; required for confirmed memory")
    parser.add_argument("--confidence", choices=("confirmed", "tentative"), default="confirmed")
    parser.add_argument("--valid-until", help="Optional ISO-8601 expiry datetime")
    parser.add_argument("--supersedes", action="append", default=[], help="Repeatable current entry ID replaced by this memory")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="UAMS tool-neutral long-term memory adapter")
    parser.add_argument("--uams-root", type=Path, default=DEFAULT_UAMS_ROOT, help="Canonical UAMS root")
    parser.add_argument("--ai-identity", required=True, help="Registered integration identity, e.g. claude, kiro, codex or k3")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="Show write authority and registered projects")
    status.set_defaults(handler=command_status)
    discover = subparsers.add_parser("discover", help="Return machine-readable UAMS entry information")
    discover.set_defaults(handler=command_discover)
    health = subparsers.add_parser("health", help="Check derived index health")
    health.add_argument("--repair", action="store_true", help="Rebuild derived indexes from canonical entries")
    health.set_defaults(handler=command_health)

    register = subparsers.add_parser("register-project", help="Safely register a project or add workspace aliases")
    register.add_argument("--project-path", required=True)
    register.add_argument("--workspace-alias", action="append", default=[])
    register.add_argument("--project-id")
    register.set_defaults(handler=command_register_project)

    read = subparsers.add_parser("read", help="Read visible memory through Gateway")
    read.add_argument("--scope", choices=("global", "project-active", "project-archive", "default", "historical-snapshot"), default="global")
    read.add_argument("--archive-query")
    add_project_options(read)
    read.set_defaults(handler=command_read)

    search = subparsers.add_parser("search", help="Precision retrieval over visible active memory")
    search.add_argument("query")
    search.add_argument("--scope", choices=("global", "project-active", "project", "default"), default="global")
    search.add_argument("--limit", type=int, default=8)
    add_project_options(search)
    add_search_filter_options(search)
    search.set_defaults(handler=command_search)

    write = subparsers.add_parser("write", help="Write governed structured long-term memory")
    write.add_argument("--title", required=True)
    write.add_argument("--body", required=True)
    add_project_options(write)
    add_metadata_options(write)
    write.set_defaults(handler=command_write)

    archive = subparsers.add_parser("archive", help="Archive a project-active memory")
    archive.add_argument("--entry-id", required=True)
    add_project_options(archive, required=True)
    archive.set_defaults(handler=command_archive)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    args.uams_root = args.uams_root.resolve()
    try:
        return args.handler(args)
    except (ProjectNotFound, ProjectConflict, ValueError, RuntimeError) as error:
        print(f"UAMS operation failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Kiro 对 UAMS 的唯一命令行适配器。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

UAMS_ROOT = Path(__file__).resolve().parents[2]
if str(UAMS_ROOT) not in sys.path:
    sys.path.insert(0, str(UAMS_ROOT))

from uams.adapters import RegisteredAIIntegrationAdapter
from uams.services import MemoryGateway, ProjectConflict, ProjectNotFound, ProjectRegistry
from uams.services.migration_history import MigrationHistoryReader
from uams.services.write_source_state import WriteSourceStateManager


def build_adapter() -> tuple[RegisteredAIIntegrationAdapter, ProjectRegistry, WriteSourceStateManager]:
    import os
    # 支持多 AI 身份：UAMS_AI_IDENTITY 环境变量（claude/kiro/codex/k3），默认 kiro
    identity = os.environ.get("UAMS_AI_IDENTITY", "kiro")
    registry = ProjectRegistry(UAMS_ROOT)
    write_state = WriteSourceStateManager(str(UAMS_ROOT))
    gateway = MemoryGateway(UAMS_ROOT, project_registry=registry, write_source_state_manager=write_state)
    return RegisteredAIIntegrationAdapter(gateway, identity), registry, write_state


def emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def entry_data(entry: Any) -> dict[str, Any]:
    return entry.to_dict() if hasattr(entry, "to_dict") else dict(entry)


def migration_reader(write_state: WriteSourceStateManager) -> MigrationHistoryReader:
    state = write_state.get_state()
    if not state.manifestId:
        raise ValueError("当前 UAMS 写入状态没有关联迁移 manifest")
    return MigrationHistoryReader(UAMS_ROOT, state.manifestId)


def command_status(_: argparse.Namespace) -> int:
    adapter, registry, write_state = build_adapter()
    emit({
        "uamsRoot": str(UAMS_ROOT),
        "aiIdentity": adapter.ai_identity,
        "uamsAuthoritative": write_state.is_uams_authoritative(),
        "registeredProjects": [record.to_dict() for record in registry.list_projects()],
    })
    return 0


def command_migration_status(_: argparse.Namespace) -> int:
    _, _, write_state = build_adapter()
    emit(migration_reader(write_state).summary())
    return 0


def command_migration_search(args: argparse.Namespace) -> int:
    _, _, write_state = build_adapter()
    reader = migration_reader(write_state)
    emit({
        "manifestId": reader.manifest_id,
        "query": args.query,
        "matches": reader.search(args.query, args.limit),
    })
    return 0


def command_migration_read(args: argparse.Namespace) -> int:
    _, _, write_state = build_adapter()
    emit(migration_reader(write_state).read_text(args.relative_path, args.max_chars))
    return 0


def command_register_project(args: argparse.Namespace) -> int:
    _, registry, _ = build_adapter()
    try:
        existing = registry.resolve(project_path=args.project_path)
    except ProjectNotFound:
        existing = None
    if existing is not None:
        if args.project_id and args.project_id != existing.projectId:
            raise ValueError(f"项目路径已注册为 {existing.projectId}，不能改用 {args.project_id}")
        if args.workspace_alias:
            existing = registry.add_workspace_aliases(existing.projectId, args.workspace_alias)
            emit({"outcome": "aliases-updated", "project": existing.to_dict()})
        else:
            emit({"outcome": "existing", "project": existing.to_dict()})
        return 0
    for alias in args.workspace_alias:
        try:
            owner = registry.resolve(workspace_path=alias)
        except ProjectNotFound:
            continue
        raise ValueError(f"工作区别名已属于项目 {owner.projectId}，不能用于新项目注册：{alias}")
    record = registry.register(args.project_path, workspace_aliases=args.workspace_alias, project_id=args.project_id)
    emit({"outcome": "registered", "project": record.to_dict()})
    return 0


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
    payload: dict[str, Any] = {}
    if args.memory_type:
        payload["memoryType"] = args.memory_type
    if args.subject:
        payload["subject"] = args.subject
    if args.tag:
        payload["tags"] = args.tag
    if args.source:
        payload["source"] = args.source
    if args.confidence:
        payload["confidence"] = args.confidence
    if args.valid_until:
        payload["validUntil"] = args.valid_until
    if args.supersedes:
        payload["supersedes"] = args.supersedes
    return payload


def command_read(args: argparse.Namespace) -> int:
    adapter, _, _ = build_adapter()
    entries = adapter.read(scope=args.scope, archive_query=args.archive_query, **project_context(args))
    if isinstance(entries, bytes):
        sys.stdout.buffer.write(entries)
        return 0
    emit({"scope": args.scope, "entries": [entry_data(entry) for entry in entries]})
    return 0


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


def command_search(args: argparse.Namespace) -> int:
    adapter, _, _ = build_adapter()
    entries = adapter.search(
        args.query,
        scope=args.scope,
        limit=args.limit,
        **project_context(args),
        **search_filter_payload(args),
    )
    emit({"query": args.query, "scope": args.scope, "entries": [entry_data(entry) for entry in entries]})
    return 0


def command_health(args: argparse.Namespace) -> int:
    adapter, _, _ = build_adapter()
    emit(adapter.health(repair=args.repair))
    return 0


def command_write(args: argparse.Namespace) -> int:
    adapter, _, _ = build_adapter()
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
    adapter, _, _ = build_adapter()
    decision = adapter.archive(args.entry_id, **project_context(args))
    emit({"outcome": decision.outcome, "entryId": decision.entryId, "targetLayer": decision.targetLayer, "resolvedProjectId": decision.resolvedProjectId})
    return 0


def add_project_options(parser: argparse.ArgumentParser, required: bool = False) -> None:
    parser.add_argument("--project-id", required=required, help="已注册的 UAMS 项目 ID")
    parser.add_argument("--project-path", help="已注册项目的绝对路径")
    parser.add_argument("--workspace-path", help="已注册的工作区别名路径")


def add_search_filter_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--type", dest="memory_type", help="精确筛选记忆类型")
    parser.add_argument("--subject", help="按主题筛选")
    parser.add_argument("--tag", action="append", default=[], help="可重复指定；结果必须包含全部标签")
    parser.add_argument("--source", help="按来源筛选")
    parser.add_argument("--confidence", choices=("confirmed", "tentative"), help="按置信度筛选")


def add_metadata_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--type", dest="memory_type", default="note", help="记忆类型，例如 decision、hardware、protocol、bug")
    parser.add_argument("--subject", help="稳定的主题或实体名称")
    parser.add_argument("--tag", action="append", default=[], help="可重复指定的检索标签")
    parser.add_argument("--source", help="事实来源，例如文件路径、测试或用户确认")
    parser.add_argument("--confidence", choices=("confirmed", "tentative"), default="confirmed")
    parser.add_argument("--valid-until", help="可选 ISO-8601 到期时间")
    parser.add_argument("--supersedes", action="append", default=[], help="可重复指定被替代的同范围活跃条目 ID")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kiro 的 UAMS 长期记忆适配器")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="查看 UAMS 写入状态与已注册项目")
    status.set_defaults(handler=command_status)

    migration_status = subparsers.add_parser("migration-status", help="查看已验收迁移的副本保全状态")
    migration_status.set_defaults(handler=command_migration_status)
    migration_search = subparsers.add_parser("migration-search", help="仅按路径元数据检索已迁移历史副本")
    migration_search.add_argument("query", help="历史项目或路径关键词，例如 motormind")
    migration_search.add_argument("--limit", type=int, default=20)
    migration_search.set_defaults(handler=command_migration_search)
    migration_read = subparsers.add_parser("migration-read", help="受限且脱敏地预览一个已迁移文本副本")
    migration_read.add_argument("--relative-path", required=True, help="migration-search 返回的精确 relativePath")
    migration_read.add_argument("--max-chars", type=int, default=8000, help="预览字符上限，最大 20000")
    migration_read.set_defaults(handler=command_migration_read)

    register = subparsers.add_parser("register-project", help="注册项目或安全追加工作区别名")
    register.add_argument("--project-path", required=True, help="项目根目录的绝对路径")
    register.add_argument("--workspace-alias", action="append", default=[], help="可重复指定的工作区别名")
    register.add_argument("--project-id", help="可选的稳定项目 ID")
    register.set_defaults(handler=command_register_project)

    read = subparsers.add_parser("read", help="通过 Gateway 读取当前可见记忆")
    read.add_argument("--scope", choices=("global", "project-active", "project-archive", "default", "historical-snapshot"), default="global")
    read.add_argument("--archive-query", help="归档查询条件，例如条目 ID")
    add_project_options(read)
    read.set_defaults(handler=command_read)

    search = subparsers.add_parser("search", help="在当前可见范围内按关键词定向检索")
    search.add_argument("query", help="问题、关键词或主题")
    search.add_argument("--scope", choices=("global", "project-active", "project", "default"), default="global")
    search.add_argument("--limit", type=int, default=8)
    add_project_options(search)
    add_search_filter_options(search)
    search.set_defaults(handler=command_search)

    health = subparsers.add_parser("health", help="检查派生索引；--repair 可从 Markdown 重建")
    health.add_argument("--repair", action="store_true", help="发现不一致时重建派生索引")
    health.set_defaults(handler=command_health)

    write = subparsers.add_parser("write", help="通过 Gateway 写入已确认的结构化长期记忆")
    write.add_argument("--title", required=True, help="简短、可检索的标题")
    write.add_argument("--body", required=True, help="已确认的事实、决定或用户明确要求记住的内容")
    add_project_options(write)
    add_metadata_options(write)
    write.set_defaults(handler=command_write)

    archive = subparsers.add_parser("archive", help="通过 Gateway 归档项目活跃记忆")
    archive.add_argument("--entry-id", required=True)
    add_project_options(archive, required=True)
    archive.set_defaults(handler=command_archive)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return args.handler(args)
    except (ProjectNotFound, ProjectConflict, ValueError, RuntimeError) as error:
        print(f"UAMS 操作失败：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

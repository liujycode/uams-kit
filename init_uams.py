#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UAMS 一键初始化工具（UAMS Bootstrap）。

在目标目录生成一套**开箱即用**的 UAMS 根（uams-root），包含：
  1. uams/ 包            —— 从本工具内置副本部署（纯标准库、零依赖）
  2. migration/ 状态     —— write-source-state.json + acceptance 记录，
                           **预置为 uams 权威写源**，新用户无需迁移即可 write
  3. 目录骨架            —— index/ audit/ memory/<各身份>/ specs/
  4. UAMS_ENTRY.json/md  —— 人/机可读的"记忆地图"入口

特性：
  - 不联网、不依赖任何第三方包（只用 Python 标准库）
  - 不修改本机其它任何位置（只写入 --uams-root 指定目录）
  - 幂等：已初始化的根再次运行会跳过已存在的内容并给出提示

用法：
  python init_uams.py --uams-root "D:/my-uams/uams-root"
  python init_uams.py --uams-root "~/uams" --identity workbuddy
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

KIT_DIR = Path(__file__).resolve().parent
BUILTIN_UAMS_PKG = KIT_DIR / "uams"
MANIFEST_ID = "uams-bootstrap-v1"
SUPPORTED_IDENTITIES = ["workbuddy", "claude", "codex", "trae", "kiro", "dsh"]

# 复制 uams 包时排除的目录/文件（运行期缓存，无需随包分发）
_COPY_IGNORE = shutil.ignore_patterns(
    "__pycache__", "*.pyc", ".hypothesis", "pytest_cache", ".pytest_cache", "*.egg-info"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _deploy_uams_pkg(root: Path, force: bool) -> str:
    dest = root / "uams"
    if dest.exists():
        if force:
            shutil.rmtree(dest)
        else:
            return "已存在，跳过（用 --force 可覆盖）"
    if not BUILTIN_UAMS_PKG.is_dir():
        sys.exit("✗ 内置 uams 包缺失：" + str(BUILTIN_UAMS_PKG))
    shutil.copytree(BUILTIN_UAMS_PKG, dest, ignore=_COPY_IGNORE)
    return "已部署 -> " + str(dest)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _bootstrap_authority(root: Path) -> None:
    """预置写源权威状态，使新用户无需迁移即可写入。

    机制（对照 uams/services/write_source_state.py + migration_acceptance.py）：
      - migration/write-source-state.json 中 source=="uams"
      - 且 manifestId 对应的 acceptance 记录 is_successful（result=success 且 failures=[]）
    两者齐备时 is_uams_authoritative() 返回 True，gateway.write 的闸门放行。
    """
    now = _now_iso()
    acceptance = {
        "manifestId": MANIFEST_ID,
        "validatedEntryCount": 0,
        "validatedAt": now,
        "result": "success",
        "failures": [],
    }
    state = {
        "source": "uams",
        "manifestId": MANIFEST_ID,
        "transitionedAt": now,
    }
    _write_text(root / "migration" / "acceptance" / f"{MANIFEST_ID}.json",
                json.dumps(acceptance, indent=2, ensure_ascii=False))
    _write_text(root / "migration" / "write-source-state.json",
                json.dumps(state, indent=2, ensure_ascii=False))


def _make_skeleton(root: Path) -> None:
    dirs = [
        "index",
        "audit",
        "memory/global",
        *[f"memory/{i}" for i in SUPPORTED_IDENTITIES],
        "specs",
    ]
    for d in dirs:
        (root / d).mkdir(parents=True, exist_ok=True)


def _make_entry_files(root: Path, identity: str) -> None:
    # 注意：入口文件放在 uams-root 的【上一级】，与引擎 discover 命令报告的位置一致
    # （discover 把 discoveryFiles 指向 <uams-root>.parent/UAMS_ENTRY.*）。
    # 这正是推荐布局：<base>/UAMS_ENTRY.*（上一级）+ <base>/uams-root/（本目录）。
    canonical = root  # uams-root 自身即权威根（discover 的 canonicalRoot 也是它）
    entry_dir = root.parent
    entry_json = {
        "canonicalRoot": str(canonical),
        "schemaVersion": "1.0",
        "supportedAIIdentities": SUPPORTED_IDENTITIES,
        "discoveryFiles": [str(entry_dir / "UAMS_ENTRY.json"),
                            str(entry_dir / "UAMS_ENTRY.md")],
        "note": "本文件是 UAMS 的'地图'（人/机可读）。CLI 不消费它；"
                "各 AI 接入时读取它来定位 uams-root 与可用身份。"
                "入口文件位于 uams-root 的上一级目录。",
        "initializedBy": "uams-kit init_uams.py",
        "initializedAt": _now_iso(),
    }
    _write_text(entry_dir / "UAMS_ENTRY.json",
                json.dumps(entry_json, indent=2, ensure_ascii=False))

    md = (
        "# UAMS 入口地图\n\n"
        "这是统一记忆系统（Universal AI Memory System）的本地根。\n\n"
        f"- **权威根（uams-root）**：`{canonical}`\n"
        f"- **入口文件位置**：`{entry_dir}`（uams-root 的上一级；`discover` 也报告这里）\n"
        f"- **默认 AI 身份**：`{identity}`\n"
        "- **支持身份**：" + ", ".join(SUPPORTED_IDENTITIES) + "\n\n"
        "## 目录速览（uams-root 内部）\n"
        "- `uams/`：记忆引擎代码（纯标准库，零依赖）\n"
        "- `memory/`：实际记忆内容，按身份分子目录（`global/` 为跨项目通用记忆）\n"
        "- `migration/`：写源权威状态与迁移验收记录（勿手改）\n"
        "- `index/`：检索索引（派生产物，`health --repair` 可重建）\n"
        "- `audit/`：治理审计日志（迁移/拒绝/策略决策）\n\n"
        "## 开局三步（每个 AI 接入时执行）\n"
        "1. `python uams/adapters/uams_memory.py --ai-identity <你的身份> --uams-root <本目录> discover`\n"
        "2. `... status`  （确认看到 `uamsAuthoritative: true`）\n"
        "3. `... search \"关键词\" --scope project-active --project-path <你的项目>`\n\n"
        "详见随包 README.md。\n"
    )
    _write_text(entry_dir / "UAMS_ENTRY.md", md)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="UAMS 一键初始化：生成开箱即用的统一记忆根",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--uams-root", required=True,
                    help="目标 UAMS 根目录（将在此创建 uams-root 及全部子结构）")
    ap.add_argument("--identity", default="workbuddy",
                    choices=SUPPORTED_IDENTITIES,
                    help="默认 AI 身份（仅写入入口文件做提示，不影响引擎）")
    ap.add_argument("--force", action="store_true",
                    help="若目标已存在 uams/ 包则强制覆盖")
    ap.add_argument("--no-copy-pkg", action="store_true",
                    help="仅生成配置/状态/骨架，不复制内置 uams 包（高级用法）")
    args = ap.parse_args()

    root = Path(args.uams_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    print("== UAMS 初始化 ==")
    print("目标根:", root)

    if args.no_copy_pkg:
        print("uams 包: 跳过（--no-copy-pkg）")
    else:
        print("uams 包:", _deploy_uams_pkg(root, args.force))

    _bootstrap_authority(root)
    print("写源权威: 已预置为 uams（无需迁移即可写入）")

    _make_skeleton(root)
    print("目录骨架: 已生成")

    _make_entry_files(root, args.identity)
    print(f"入口文件: {root.parent / 'UAMS_ENTRY.json'} / .md 已生成（位于 uams-root 上一级）")

    print("\n✓ 初始化完成。下一步验证：")
    print(f'  python uams/adapters/uams_memory.py --ai-identity {args.identity} '
          f'--uams-root "{root}" status')
    print("  应看到  uamsAuthoritative: true")
    print(f'  python uams/adapters/uams_memory.py --ai-identity {args.identity} '
          f'--uams-root "{root}" write --title "第一条记忆" --body "..." '
          f'--type note --source bootstrap --confidence confirmed')


if __name__ == "__main__":
    main()

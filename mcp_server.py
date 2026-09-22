#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UAMS MCP Server（纯标准库，零依赖）。

把 UAMS CLI 包成 Model Context Protocol (MCP) stdio server，
让 Claude Code / Cursor / Codex / 任意 MCP 客户端"一行配置"接上同一份本地记忆。

设计原则：
  - 只用 Python 标准库（json / subprocess / threading / os / pathlib / sys / time）。
  - 不动 UAMS 引擎：所有操作都通过子进程调用 uams/adapters/uams_memory.py 完成。
  - 写/检索加跨进程 advisory 锁，防止多 agent 并发写坏 JSON。

用法：
  python mcp_server.py --uams-root "D:/my-uams/uams-root"
  python mcp_server.py --uams-root "D:/my-uams/uams-root" --ai-identity claude

MCP 客户端配置示例（Claude Desktop / Cursor）：
  {
    "mcpServers": {
      "uams": { "command": "python", "args": ["D:/uams-kit/mcp_server.py", "--uams-root", "D:/my-uams/uams-root"] }
    }
  }

协议：stdio 上逐行传输 JSON-RPC 2.0（每条消息一行，LF 结尾）。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "uams-memory"
SERVER_VERSION = "0.2.0"

# 跨进程锁的等待上限（秒）。超时后仍放行，避免死锁卡死客户端。
LOCK_TIMEOUT = 30.0
# 锁被视为"陈旧"的阈值（秒）。进程崩溃留下的锁超过这个时间会被强制清除。
LOCK_STALE_AFTER = 120.0


def _log(msg: str) -> None:
    # 日志走 stderr，保持 stdout 干净（MCP 只用 stdout 传 JSON-RPC）。
    print(f"[uams-mcp] {msg}", file=sys.stderr, flush=True)


class UamsBridge:
    """封装对 UAMS CLI 的调用，并加跨进程写锁。"""

    def __init__(self, root: Path, default_identity: str):
        self.root = root
        self.default_identity = default_identity
        self.adapter = root / "uams" / "adapters" / "uams_memory.py"
        self._lockdir = root / ".uams-write.lock"
        self._proc_lock = threading.Lock()  # 进程内串行（与跨进程锁互补）

    # ---- 跨进程 advisory 锁（原子 mkdir 实现，全平台可用）----
    def _acquire(self) -> bool:
        deadline = time.time() + LOCK_TIMEOUT
        while True:
            try:
                self._lockdir.mkdir(parents=True, exist_ok=False)
                return True
            except FileExistsError:
                try:
                    age = time.time() - self._lockdir.stat().st_mtime
                    if age > LOCK_STALE_AFTER:
                        import shutil
                        shutil.rmtree(self._lockdir, ignore_errors=True)
                        continue
                except FileNotFoundError:
                    continue
                if time.time() > deadline:
                    _log("写锁等待超时，强制放行（可能并发）")
                    return True
                time.sleep(0.05)

    def _release(self) -> None:
        try:
            self._lockdir.rmdir()
        except OSError:
            pass

    def _guarded(self, fn):
        with self._proc_lock:
            self._acquire()
            try:
                return fn()
            finally:
                self._release()

    # ---- CLI 调用 ----
    def _run(self, identity: str, *cli_args: str) -> tuple[bool, str]:
        if not self.adapter.is_file():
            return False, f"✗ 找不到引擎：{self.adapter}\n请先运行 init_uams.py 初始化 uams-root。"
        cmd = [sys.executable, str(self.adapter),
               "--ai-identity", identity, "--uams-root", str(self.root), *cli_args]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            return False, "✗ UAMS CLI 执行超时（>120s）"
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        text = out + (("\n--- stderr ---\n" + err) if err and not out else "")
        return r.returncode == 0, text.strip() or "(无输出)"

    # ---- 四个工具 ----
    def discover(self, identity: str) -> tuple[bool, str]:
        return self._run(identity, "discover")

    def status(self, identity: str) -> tuple[bool, str]:
        return self._run(identity, "status")

    def search(self, query: str, scope: str | None, project_path: str | None,
               identity: str) -> tuple[bool, str]:
        args = ["search", query]
        if scope:
            args += ["--scope", scope]
        if project_path:
            args += ["--project-path", project_path]
        return self._guarded(lambda: self._run(identity, *args))

    def write(self, title: str, body: str, type_: str | None, source: str | None,
              confidence: str | None, subject: str | None, project_path: str | None,
              supersedes: str | None, identity: str) -> tuple[bool, str]:
        args = ["write", "--title", title, "--body", body]
        if type_:
            args += ["--type", type_]
        if source:
            args += ["--source", source]
        if confidence:
            args += ["--confidence", confidence]
        if subject:
            args += ["--subject", subject]
        if project_path:
            args += ["--project-path", project_path]
        if supersedes:
            args += ["--supersedes", supersedes]

        def _do():
            ok, text = self._run(identity, *args)
            return ok, text

        return self._guarded(_do)


# ---------------------------------------------------------------------------
# MCP 工具定义
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "uams_discover",
        "description": "定位 UAMS 根（canonicalRoot）、列出支持的身份。每个 AI 接记忆前先跑一次。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ai_identity": {
                    "type": "string",
                    "description": "AI 身份，默认取服务器配置。可选：workbuddy|claude|codex|trae|kiro|dsh",
                }
            },
        },
    },
    {
        "name": "uams_status",
        "description": "显示 UAMS 权威状态、版本、已注册项目。写之前必须确认 uamsAuthoritative: true。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ai_identity": {"type": "string", "description": "AI 身份（可选）"}
            },
        },
    },
    {
        "name": "uams_search",
        "description": "检索记忆。工具无关：不按身份过滤，workbuddy 写的内容 claude 也能搜到。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索关键词"},
                "scope": {
                    "type": "string",
                    "description": "检索范围：global / project-active（默认） / default / historical-snapshot",
                },
                "project_path": {"type": "string", "description": "项目根目录（检索项目记忆时给）"},
                "ai_identity": {"type": "string", "description": "AI 身份（可选）"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "uams_write",
        "description": "写入一条记忆。写前请先 uams_status 确认权威；同主题更新用 supersedes 替代旧条目。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "记忆标题"},
                "body": {"type": "string", "description": "记忆正文"},
                "type": {
                    "type": "string",
                    "description": "类型：note / preference / decision / convention / rule 等。非 note 必填 subject",
                },
                "source": {"type": "string", "description": "来源：user-stated / discussion / bootstrap / verified 等（confirmed 时必填）"},
                "confidence": {"type": "string", "description": "置信度：confirmed / inferred / tentative"},
                "subject": {"type": "string", "description": "稳定主题路径（非 note 类型必填），如 '架构/xx'"},
                "project_path": {"type": "string", "description": "项目根目录（写项目记忆时给，需先 register-project）"},
                "supersedes": {"type": "string", "description": "要替代的旧 entryId（同主题更新用）"},
                "ai_identity": {"type": "string", "description": "AI 身份（可选）"},
            },
            "required": ["title", "body"],
        },
    },
]


def _tool_result(text: str, is_error: bool) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


# ---------------------------------------------------------------------------
# 请求分发
# ---------------------------------------------------------------------------

def handle(msg: dict, bridge: UamsBridge, default_identity: str) -> dict | None:
    method = msg.get("method")
    msg_id = msg.get("id")

    # 通知类（无 id）不回包
    if msg_id is None:
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        name = (msg.get("params") or {}).get("name")
        args = (msg.get("params") or {}).get("arguments") or {}
        identity = args.get("ai_identity") or default_identity
        try:
            if name == "uams_discover":
                ok, text = bridge.discover(identity)
            elif name == "uams_status":
                ok, text = bridge.status(identity)
            elif name == "uams_search":
                ok, text = bridge.search(
                    args.get("query", ""), args.get("scope"),
                    args.get("project_path"), identity)
            elif name == "uams_write":
                ok, text = bridge.write(
                    args.get("title", ""), args.get("body", ""),
                    args.get("type"), args.get("source"), args.get("confidence"),
                    args.get("subject"), args.get("project_path"),
                    args.get("supersedes"), identity)
            else:
                return {
                    "jsonrpc": "2.0", "id": msg_id,
                    "error": {"code": -32601, "message": f"未知工具: {name}"},
                }
        except Exception as e:  # 任何异常都转成 isError，不让 server 崩
            return {
                "jsonrpc": "2.0", "id": msg_id,
                "result": _tool_result(f"✗ 调用异常：{e}", True),
            }
        return {"jsonrpc": "2.0", "id": msg_id, "result": _tool_result(text, not ok)}

    # 未知方法
    return {
        "jsonrpc": "2.0", "id": msg_id,
        "error": {"code": -32601, "message": f"不支持的方法: {method}"},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="UAMS MCP Server（stdio，纯标准库）")
    ap.add_argument("--uams-root", default=os.environ.get("UAMS_ROOT"),
                    help="UAMS 根目录（也可用环境变量 UAMS_ROOT）")
    ap.add_argument("--ai-identity", default=os.environ.get("UAMS_AI_IDENTITY", "workbuddy"),
                    help="默认 AI 身份（工具可逐次覆盖）")
    args = ap.parse_args()

    if not args.uams_root:
        _log("ERROR: 必须提供 --uams-root 或环境变量 UAMS_ROOT")
        sys.exit(2)

    root = Path(args.uams_root).expanduser().resolve()
    if not root.is_dir():
        _log(f"ERROR: uams-root 不存在：{root}（请先运行 init_uams.py）")
        sys.exit(2)

    bridge = UamsBridge(root, args.ai_identity)
    _log(f"启动：root={root} identity={args.ai_identity}")

    # stdio 主循环：逐行读 JSON-RPC，回写 JSON-RPC
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            resp = handle(msg, bridge, args.ai_identity)
        except Exception as e:
            _log(f"分发异常：{e}")
            resp = None
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()

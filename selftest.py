#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UAMS 分享工具包 —— 自检脚本
========================
在隔离沙盒里跑完整链路，验证 kit 真能用，不碰你任何已有数据。

覆盖:
  [✓] init_uams 初始化
  [✓] UAMS_ENTRY 入口文件位置对齐 discover（P1 修复）
  [✓] MCP server: initialize / tools/list / 4 个工具
  [✓] write -> 换身份 search 读回（工具无关性，经 MCP 通道）
  [✓] 并发写安全（跨进程锁）
  [·] 引擎副本 vs 你自己的 UAMS 是否一致（可选，--live-uams 只读比对）

用法:
  python selftest.py                  # 临时沙盒（默认跳过引擎比对）
  python selftest.py --uams-root DIR  # 验证你已初始化的目录（不覆盖）
  python selftest.py --live-uams DIR  # 比对你的真实 UAMS 引擎（只读）
  python selftest.py --no-drift       # 跳过引擎副本比对
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parent
PY = sys.executable
# 仅用于只读比对（可选）。用 --live-uams 指定你自己的真实 UAMS 引擎路径；
# 不指定则跳过比对，不影响其他自检项。
LIVE_UAMS = None

fails = []


def check(cond, label, extra=""):
    mark = "✓ PASS " if cond else "✗ FAIL "
    tail = f"  ({extra})" if (extra and not cond) else ""
    print(mark + label + tail)
    if not cond:
        fails.append(label)


def sendp(proc, obj):
    proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
    proc.stdin.flush()


def recvp(proc):
    for _ in range(80):
        line = proc.stdout.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return None


def mcp_session(root, identity=None):
    cmd = [PY, str(KIT / "mcp_server.py"), "--uams-root", str(root)]
    if identity:
        cmd += ["--identity", identity]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            text=True, bufsize=1)


def drift_check(live):
    if live is None:
        print("· 跳过引擎比对：未指定 --live-uams（可选，用于比对你的真实 UAMS）")
        return
    if not live.exists():
        print("· 跳过引擎比对：指定路径不存在（用 --live-uams 指定正确路径）")
        return
    if not (KIT / "uams").exists():
        print("· 跳过引擎比对：kit 内无 uams/ 目录")
        return

    def hashes(p):
        h = {}
        for f in p.rglob("*.py"):
            h[str(f.relative_to(p))] = hashlib.sha256(f.read_bytes()).hexdigest()
        return h

    kh, lh = hashes(KIT / "uams"), hashes(live)
    added = set(kh) - set(lh)
    removed = set(lh) - set(kh)
    changed = [k for k in (set(kh) & set(lh)) if kh[k] != lh[k]]
    if not (added or removed or changed):
        print("✓ PASS 引擎副本与本机 UAMS 一致（无漂移）")
    else:
        print("· INFO 引擎副本与本机有差异: "
              f"+{sorted(added)} -{sorted(removed)} ~{changed}")
        print("         kit 是快照，如需同步请刷新 uams/ 目录")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uams-root", default=None,
                    help="已初始化的目录；不传则用临时沙盒")
    ap.add_argument("--live-uams", default=None,
                    help="本机 UAMS 引擎路径，用于只读比对")
    ap.add_argument("--no-drift", action="store_true")
    args = ap.parse_args()

    live = Path(args.live_uams) if args.live_uams else LIVE_UAMS

    if args.uams_root:
        root = Path(args.uams_root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        sandbox = False
    else:
        base = Path(tempfile.mkdtemp(prefix="uams_selftest_"))
        root = base / "uams-root"
        root.mkdir(parents=True, exist_ok=True)
        sandbox = True

    try:
        # 1. 初始化（已存在则复用，绝不覆盖）
        if (root / "uams" / "adapters" / "uams_memory.py").is_file():
            print(f"· 复用已有初始化: {root}")
        else:
            r = subprocess.run([PY, str(KIT / "init_uams.py"),
                                "--uams-root", str(root)],
                               capture_output=True, text=True, timeout=180)
            check(r.returncode == 0, "init_uams 初始化", r.stderr[-200:])
        check((root / "uams" / "adapters" / "uams_memory.py").is_file(),
              "引擎已部署")

        # 2. P1 入口位置对齐 discover
        entry = root.parent / "UAMS_ENTRY.json"
        check(entry.is_file(),
              "UAMS_ENTRY 在 uams-root 上一级（对齐 discover）", str(entry))

        # 3. MCP 握手
        p = mcp_session(root)
        sendp(p, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": "2024-11-05",
                             "capabilities": {},
                             "clientInfo": {"name": "selftest", "version": "1"}}})
        resp = recvp(p)
        check(resp and resp.get("id") == 1 and
              resp.get("result", {}).get("protocolVersion") == "2024-11-05",
              "MCP initialize", resp)
        sendp(p, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        sendp(p, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        resp = recvp(p)
        tools = [t["name"] for t in (resp or {}).get("result", {}).get("tools", [])]
        check(set(tools) == {"uams_discover", "uams_status",
                             "uams_search", "uams_write"},
              "MCP 暴露 4 个工具", tools)

        # 4. write -> 换 claude 身份 search 读回
        sendp(p, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                  "params": {"name": "uams_write",
                             "arguments": {"title": "跨身份自检记忆",
                                           "body": "自检写入", "type": "note",
                                           "source": "bootstrap",
                                           "confidence": "confirmed"}}})
        resp = recvp(p)
        check(resp and (resp.get("result") or {}).get("isError") is False,
              "uams_write 成功",
              ((resp.get("result", {}).get("content", [{}])[0].get("text", ""))
               if resp else "")[:120])
        # 注意：引擎 search 按"词元"匹配、不支持子串。这里用写入时的完整标题词元做查询。
        sendp(p, {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                  "params": {"name": "uams_search",
                             "arguments": {"query": "跨身份自检记忆",
                                           "scope": "global",
                                           "ai_identity": "claude"}}})
        resp = recvp(p)
        txt = (resp.get("result", {}).get("content", [{}])[0].get("text", "")
               if resp else "")
        check("跨身份自检记忆" in txt,
              "uams_search 换 claude 身份读回（工具无关性）", txt[:120])

        # 5. 并发写安全（N 个 server 同时抢锁）
        N = 6
        procs = [mcp_session(root) for _ in range(N)]
        for pp in procs:
            sendp(pp, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"protocolVersion": "2024-11-05",
                                  "capabilities": {},
                                  "clientInfo": {"name": "c", "version": "1"}}})
            recvp(pp)
            sendp(pp, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        for i, pp in enumerate(procs):
            sendp(pp, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                      "params": {"name": "uams_write",
                                 "arguments": {"title": f"并发-{i}",
                                               "body": f"worker {i}",
                                               "type": "note",
                                               "source": "bootstrap",
                                               "confidence": "confirmed"}}})
            recvp(pp)
        for pp in procs:
            pp.terminate()
        p2 = mcp_session(root)
        sendp(p2, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {"protocolVersion": "2024-11-05",
                              "capabilities": {},
                              "clientInfo": {"name": "c", "version": "1"}}})
        recvp(p2)
        sendp(p2, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        sendp(p2, {"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                   "params": {"name": "uams_search",
                              "arguments": {"query": "并发-", "scope": "global"}}})
        resp = recvp(p2)
        txt = (resp.get("result", {}).get("content", [{}])[0].get("text", "")
               if resp else "")
        found = sum(1 for i in range(N) if f"并发-{i}" in txt)
        check(found == N, f"并发写后 {N} 条全在、无损坏", f"found={found}")
        p2.terminate()
        p.terminate()

        # 6. 引擎副本比对
        if not args.no_drift:
            drift_check(live)

    finally:
        if sandbox:
            shutil.rmtree(base, ignore_errors=True)

    print("\n==== 自检结果 ====")
    if fails:
        print("有失败项:", fails)
        sys.exit(1)
    print("全部通过 ✓")


if __name__ == "__main__":
    main()

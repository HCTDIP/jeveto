#!/usr/bin/env python3
"""零依赖 MCP 客户端（stdio / JSON-RPC 2.0）。

为什么自己写：官方 `mcp` Python SDK 要装依赖，而我们要的东西很小 ——
    initialize → notifications/initialized → tools/list → tools/call
手写 60 行就够，且能直接在手机上跑、能对着我们**已有的** MCP 服务器（node 版 filesystem/github）验证。

协议要点：
  · stdio 传输 = 每行一个 JSON（换行分隔），不是 LSP 的 Content-Length 头
  · 先 initialize，再发 notifications/initialized，之后才能 tools/list / tools/call
  · 与服务器成对启停（用 with 语句或 close()）

用法：
    with MCPClient(["node", ".../server-filesystem/dist/index.js", "/path/to/shared"]) as c:
        print(c.list_tools())
        print(c.call_tool("list_directory", {"path": "/path/to/shared"}))
"""
import json
import os
import subprocess
import threading
import time


class MCPError(RuntimeError):
    pass


class MCPClient:
    def __init__(self, command: list, env: dict = None, name: str = "jeveto", version: str = "0.2.0",
                 timeout: float = 30.0):
        self.command = command
        self.timeout = timeout
        self._id = 0
        self._lock = threading.Lock()
        e = dict(os.environ)
        e.update(env or {})
        self.proc = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=e, text=True, bufsize=1,
        )
        self._initialize(name, version)

    # ---------- 传输 ----------
    def _send(self, obj: dict):
        line = json.dumps(obj, ensure_ascii=False) + "\n"
        with self._lock:
            self.proc.stdin.write(line)
            self.proc.stdin.flush()

    def _read(self):
        line = self.proc.stdout.readline()
        if not line:
            err = (self.proc.stderr.read() or "")[:400] if self.proc.stderr else ""
            raise MCPError(f"MCP 服务器提前退出（exit={self.proc.poll()}）: {err}")
        return json.loads(line)

    def _request(self, method: str, params: dict = None):
        self._id += 1
        rid = self._id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            msg = self._read()
            if msg.get("id") != rid:
                continue                      # 忽略通知/其它响应
            if "error" in msg:
                raise MCPError(f"{method} 失败: {msg['error']}")
            return msg.get("result", {})
        raise MCPError(f"{method} 超时（{self.timeout}s）")

    def _notify(self, method: str, params: dict = None):
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    # ---------- 握手 ----------
    def _initialize(self, name: str, version: str):
        self.server_info = self._request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": name, "version": version},
        })
        self._notify("notifications/initialized")

    # ---------- API ----------
    def list_tools(self) -> list:
        return self._request("tools/list", {}).get("tools", [])

    def call_tool(self, tool: str, arguments: dict = None):
        res = self._request("tools/call", {"name": tool, "arguments": arguments or {}})
        parts = []
        for c in res.get("content", []):
            parts.append(c.get("text") if c.get("type") == "text" else json.dumps(c, ensure_ascii=False))
        return {"text": "\n".join(p for p in parts if p is not None),
                "is_error": bool(res.get("isError")), "raw": res}

    def close(self):
        try:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


# ---------- Example MCP server list (align with your own servers.json) ----------
NODE_DIR = os.environ.get("MCP_NODE_DIR", "/root/mcp-node/node_modules/@modelcontextprotocol")


def filesystem_server(roots: list = None):
    return ["node", f"{NODE_DIR}/server-filesystem/dist/index.js",
            *(roots or ["/path/to/workspace", "/path/to/shared"])]


def github_server():
    return ["node", f"{NODE_DIR}/server-github/dist/index.js"]


def connect(kind: str, token: str = None, roots: list = None) -> MCPClient:
    if kind == "filesystem":
        return MCPClient(filesystem_server(roots))
    if kind == "github":
        t = token or os.environ.get("GITHUB_TOKEN")
        if not t:
            raise MCPError("github MCP 需要 GITHUB_TOKEN")
        return MCPClient(github_server(), env={"GITHUB_PERSONAL_ACCESS_TOKEN": t})
    raise MCPError(f"未知 MCP 服务器: {kind}")


if __name__ == "__main__":
    import sys
    kind = sys.argv[1] if len(sys.argv) > 1 else "filesystem"
    with connect(kind) as c:
        info = c.server_info.get("serverInfo", {})
        print(f"[MCP] {kind} 已连接: {info.get('name')} {info.get('version')} "
              f"(protocol {c.server_info.get('protocolVersion')})")
        tools = c.list_tools()
        print(f"[MCP] 暴露 {len(tools)} 个工具:")
        for t in tools[:12]:
            print(f"   · {t['name']}: {(t.get('description') or '')[:64]}")
        if kind == "filesystem":
            out = c.call_tool("list_directory", {"path": "/path/to/shared"})
            print("[MCP] 真调用 list_directory /path/to/shared →")
            print("   " + (out["text"] or "")[:280].replace("\n", "\n   "))

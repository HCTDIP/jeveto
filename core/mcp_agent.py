#!/usr/bin/env python3
"""把 MCP 工具挂成 jeveto 的 agent 执行体（零成本线之二）。

约定：agent.endpoint = `mcp://<server>/<tool>`，例如
    mcp://filesystem/list_directory
    mcp://github/create_pull_request

参数来源：payload 里的 `arguments`（推荐），否则把 payload 去掉框架字段后整体当参数，
并可给 agent 配 `tags=["mcp:<server>", "tool:<tool>"]` 便于路由。

与既有执行体契约一致：返回 dict（status/agent/summary/...），上游 ChiefOfStaff 与 /api/ask 直接用。
"""
import asyncio
import json

from .mcp_client import MCPError, connect

FRAMEWORK_KEYS = {"task", "completed_work", "goal", "q"}


def parse_mcp_endpoint(endpoint: str):
    if not endpoint or not endpoint.startswith("mcp://"):
        return None
    body = endpoint[len("mcp://"):]
    if "/" not in body:
        raise MCPError(f"endpoint 形状应为 mcp://<server>/<tool>，收到：{endpoint}")
    kind, tool = body.split("/", 1)
    return kind, tool


def _call_sync(kind: str, tool: str, arguments: dict):
    with connect(kind) as c:
        return c.call_tool(tool, arguments)


async def make_mcp_executor(agent, payload: dict):
    """非 MCP agent 返回 None（交给后面的执行体），是 MCP agent 则真调用。"""
    parsed = parse_mcp_endpoint(getattr(agent, "endpoint", None) or "")
    if not parsed:
        return None
    kind, tool = parsed
    arguments = payload.get("arguments") or {k: v for k, v in payload.items() if k not in FRAMEWORK_KEYS}
    try:
        out = await asyncio.to_thread(_call_sync, kind, tool, arguments)   # subprocess 是阻塞的，别卡事件循环
        text = (out.get("text") or "").strip()
        return {"status": "live", "agent": agent.title, "transport": "mcp",
                "server": kind, "tool": tool, "arguments": arguments,
                "is_error": out.get("is_error"), "summary": text[:500],
                "summary_chars": len(text)}
    except Exception as e:
        return {"status": "error", "agent": agent.title, "transport": "mcp",
                "server": kind, "tool": tool, "error": str(e)[:200]}


# ---------- 幂等注册（让干净部署不再是空壳） ----------
MCP_AGENTS = [
    {"title": "MCPFilesystem", "description": "读/写/搜本地挂载目录（MCP filesystem 服务器）",
     "source_url": "https://github.com/modelcontextprotocol/servers",
     "capabilities": ["files"], "avg_cost": 0.0, "avg_latency": 120.0, "priority": 3,
     "tags": ["mcp", "filesystem"], "status": "active", "endpoint": "mcp://filesystem/list_directory"},
    {"title": "MCPGitHub", "description": "GitHub 读写：建分支/提交/开 PR/搜仓（MCP github 服务器）",
     "source_url": "https://github.com/github/github-mcp-server",
     "capabilities": ["github"], "avg_cost": 0.0, "avg_latency": 400.0, "priority": 3,
     "tags": ["mcp", "github"], "status": "active", "endpoint": "mcp://github/search_repositories"},
]


def register_mcp_agents(db) -> list:
    """幂等：已存在就跳过。返回本次新建的标题列表。"""
    from .models import Agent
    created = []
    for spec in MCP_AGENTS:
        if db.query(Agent).filter(Agent.title == spec["title"]).first():
            continue
        db.add(Agent(**spec))
        created.append(spec["title"])
    if created:
        db.commit()
    return created


if __name__ == "__main__":
    import sys

    from .database import SessionLocal

    if len(sys.argv) > 1 and sys.argv[1] == "register":
        print("registered:", register_mcp_agents(SessionLocal()))
    else:
        ep = sys.argv[1] if len(sys.argv) > 1 else "mcp://filesystem/list_directory"
        args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {"path": "/var/minis/shared"}
        kind, tool = parse_mcp_endpoint(ep)
        out = _call_sync(kind, tool, args)
        print(f"[MCP] {ep} {args} → is_error={out['is_error']}")
        print((out["text"] or "")[:400])

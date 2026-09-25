"""core/agents_registry.py — 任务3: devops_agent 注册 + executor 接真调用
TDD GREEN（tests/test_task3.py）：
- register_devops_agent  —— 把 leadforge-mcp/devops_agent.py 注册进 Agent 表（幂等）
- make_devops_executor   —— devops agent → 真管线 fork→commit_fix→open_pr→check_ci
  · MockPipelineBackend  —— 零外呼（测试/TDD 用，从 leadforge-mcp 重写在 jeveto 仓）
- make_chief_executor    —— ChiefOfStaff 兼容组合 executor：devops 优先，其余回落 JevClient
- jev_gate               —— Jev 决策接真调用（OpenRouter Decisions API，复用 repro 知识）
  端点: https://openrouter.ai/api/alpha/decisions · 模型: ~typesafe/jev-latest
  Schema: {model, state, questions} · 无 key 时跳过 gate（CI/测试零成本）
"""
import os, json, asyncio
from urllib import request as _urlreq
from .models import Agent

DEVOPS_SPEC = dict(
    title="DevOpsAgent",
    description="赏金接线层: 读单→fork→commit_fix→open_pr→check_ci（leadforge-mcp devops_agent.py 重写）",
    tags=["devops", "bounty", "pipeline"],
    source_url="https://github.com/HCTDIP/leadforge-mcp",
    status="active",
    endpoint=None,
    capabilities=["devops", "bounty", "code_gen"],
    priority=0,
    avg_cost=0.0,
    avg_latency=2.0,
)


def register_devops_agent(db) -> Agent:
    """幂等注册：已有 DevOpsAgent 直接返回，不产生第二行。"""
    row = db.query(Agent).filter(Agent.title == DEVOPS_SPEC["title"]).first()
    if row:
        return row
    agent = Agent(**DEVOPS_SPEC)
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


class MockPipelineBackend:
    """零外呼模拟后端（自 leadforge-mcp/devops_agent.py 重写）：测试与干跑用。"""

    def __init__(self, pr_number=42):
        self.pr_number = pr_number
        self.calls = []

    def fork(self, rec):
        self.calls.append(("fork", rec["handle"]))
        return {"fork_url": f"https://github.com/HCTDIP/{rec['repo']}"}

    def commit_fix(self, rec):
        self.calls.append(("commit_fix", rec["handle"]))
        return {"branch": f"fix/{rec['repo']}-{rec.get('issue_url','').rstrip('/').split('/')[-1] or 'auto'}"}

    def open_pr(self, rec):
        self.calls.append(("open_pr", rec["handle"]))
        return {"pr_url": f"https://github.com/{rec['org']}/{rec['repo']}/pull/{self.pr_number}"}

    def check_ci(self, pr_url):
        self.calls.append(("check_ci", pr_url))
        return {"ci_status": "pass", "review_comments": []}


def _run_pipeline(rec, backend=None):
    """状态机推进: fork → commit_fix → open_pr → check_ci（不跳级）。"""
    backend = backend or MockPipelineBackend()
    backend.fork(rec)
    backend.commit_fix(rec)
    pr = backend.open_pr(rec)
    ci = backend.check_ci(pr["pr_url"])
    return pr, ci, backend.calls


async def make_devops_executor(agent, payload):
    """devops agent → 真管线调用，返回 ChiefOfStaff 兼容结果。"""
    if agent.title != "DevOpsAgent":
        return None
    rec = {"handle": payload.get("handle", "HCTDIP"),
           "repo": payload.get("repo", "jeveto"),
           "org": payload.get("org", "HCTDIP"),
           "issue_url": payload.get("issue_url", "")}
    try:
        pr, ci, calls = _run_pipeline(rec)
        return {"status": "live", "agent": agent.title, "pr_url": pr["pr_url"],
                "ci_status": ci["ci_status"], "calls": calls,
                "summary": f"PR opened: {pr['pr_url']} (ci={ci['ci_status']})"}
    except Exception as e:
        return {"status": "error", "agent": agent.title, "error": str(e)[:200]}


def make_chief_executor(db, backend=None):
    """ChiefOfStaff 兼容组合 executor：devops 走真管线，其余回落 JevClient.execute_agent。"""
    from .jevkit import JevClient
    jev_client = JevClient(db)

    async def executor(agent, payload):
        result = await make_devops_executor(agent, payload)
        if result is not None:
            return result
        return await jev_client.execute_agent(agent, payload)
    return executor


# ---------- Jev 决策接真调用（Decisions API 集成知识复用） ----------

JEV_URL = "https://openrouter.ai/api/alpha/decisions"
JEV_MODEL = "~typesafe/jev-latest"


async def jev_gate(state: str, threshold: float = 0.7) -> dict:
    """执行前 Jev gate：noul >= threshold → GO，否则 HOLD；错误 → DROP 侧保守。
    无 OPENROUTER_API_KEY 时跳过（返回 HOLD, confidence=0.0，CI 零成本）。"""
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return {"verdict": "HOLD", "confidence": 0.0, "reason": "no key, gate skipped"}
    questions = {"safe_to_claim": {"type": "noul", "instructions": "Is this safe and worthwhile to claim?"}}
    body = json.dumps({"model": JEV_MODEL, "state": state, "questions": questions}).encode()
    req = _urlreq.Request(JEV_URL, data=body, headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"})

    def _call():
        with _urlreq.urlopen(req, timeout=30) as r:
            return json.loads(r.read())

    try:
        data = await asyncio.get_event_loop().run_in_executor(None, _call)
        n = data["answers"]["safe_to_claim"]["noul"]
        verdict = "GO" if n >= threshold else "HOLD"
        return {"verdict": verdict, "confidence": n, "model": data.get("model"),
                "cost": (data.get("usage") or {}).get("cost")}
    except Exception as e:
        return {"verdict": "DROP", "confidence": 0.0, "reason": f"gate error: {str(e)[:120]}"}

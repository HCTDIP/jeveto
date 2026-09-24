from typing import Optional
import re, urllib.parse
import httpx
from .models import Agent

class JevClient:
    """Jev routing engine v2: trace + real endpoints + chain orchestration."""

    def __init__(self, db):
        self.db = db

    def _score(self, a, strategy):
        # lower is better; cost strategy: cheap wins, priority breaks ties
        if strategy == "latency":
            return (a.avg_latency or 0) - (a.priority or 0) * 0.001
        return (a.avg_cost or 0) * 100 - (a.priority or 0)

    def route_trace(self, capability: str, strategy: str = "cost") -> dict:
        agents = self.db.query(Agent).filter(Agent.status == "active").all()
        matched = [a for a in agents if capability in (a.capabilities or [])]
        if not matched:
            return {"capability": capability, "strategy": strategy,
                    "candidates": [], "winner": None, "reason": "no match"}
        winner = min(matched, key=lambda a: self._score(a, strategy))
        cands = sorted([{
            "title": a.title, "avg_cost": a.avg_cost, "avg_latency": a.avg_latency,
            "priority": a.priority, "live": bool(a.endpoint),
            "score": round(self._score(a, strategy), 3),
        } for a in matched], key=lambda c: c["score"])
        reason = (f"cost=${winner.avg_cost} prio={winner.priority}" if strategy == "cost"
                  else f"latency={winner.avg_latency}ms prio={winner.priority}")
        return {"capability": capability, "strategy": strategy,
                "candidates": cands, "winner": winner.title, "reason": reason}

    def get_best_agent(self, capability: str, strategy: str = "cost") -> Optional[Agent]:
        t = self.route_trace(capability, strategy)
        if not t["winner"]:
            return None
        return self.db.query(Agent).filter(Agent.title == t["winner"]).first()

    async def execute_agent(self, agent: Agent, payload: dict) -> dict:
        if not agent.endpoint:
            return {"status": "simulated", "agent": agent.title, "input": payload}
        url = agent.endpoint
        try:
            if "{q}" in url:  # GET template convention: real live call
                q = urllib.parse.quote(str(payload.get("q") or payload.get("task") or ""))
                async with httpx.AsyncClient(timeout=15.0, verify=False, headers={"User-Agent": "MuleRun/0.2 routing demo"}) as client:
                    resp = await client.get(url.replace("{q}", q))
                    resp.raise_for_status()
                    try:
                        data = resp.json()
                    except Exception:
                        data = None
                if isinstance(data, dict):
                    text = (data.get("AbstractText") or data.get("Definition")
                            or data.get("extract") or data.get("answer") or "")
                    if not text:
                        topics = [t.get("Text") for t in (data.get("RelatedTopics") or [])
                                  if isinstance(t, dict) and t.get("Text")][:3]
                        text = " | ".join(topics)
                else:
                    text = (resp.text or "").strip()
                summary = str(text)[:300] or "(no result)"
                return {"status": "live", "agent": agent.title, "summary": summary}
            async with httpx.AsyncClient(timeout=10.0, headers={"User-Agent": "MuleRun/0.2 routing demo"}) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                return {"status": "live", "agent": agent.title, "response": resp.text[:300]}
        except Exception as e:
            return {"status": "error", "agent": agent.title, "error": str(e)[:200]}

    CAP_MAP = [("math", r"计算|算|math|calc"),
               ("research", r"研究|百科|wiki|research|了解"),
               ("search", r"搜索|search|查|找|look ?up"),
               ("code_gen", r"代码|code|写|generate|函数")]

    async def execute_chain(self, text: str, strategy: str = "cost") -> list:
        """一句话 -> 分步 -> 每步路由到最佳 Agent -> 顺序执行"""
        steps = [s.strip() for s in re.split(r"然后|再|->|→|then|;", text) if s.strip()]
        out = []
        for step in steps:
            cap = "search"
            for c, pat in self.CAP_MAP:
                if re.search(pat, step.lower()):
                    cap = c
                    break
            trace = self.route_trace(cap, strategy)
            entry = {"step": step, **trace}
            if trace["winner"]:
                agent = self.db.query(Agent).filter(Agent.title == trace["winner"]).first()
                # strip intent prefix so the live query is clean (搜索solana -> solana)
                q = re.sub(r"^(搜索|search|查找|查|找|研究|了解|百科|计算|算一下|算)\s*", "", step, flags=re.I)
                entry["exec"] = await self.execute_agent(agent, {"q": q or step, "task": step})
            else:
                entry["exec"] = {"status": "skipped", "error": f"no agent for {cap}"}
            out.append(entry)
        return out

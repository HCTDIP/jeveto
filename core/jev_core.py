"""Jev 十步法内核 v3 —— 按 @0xCodila《Jev Engineering: 10-Step Roadmap》改造
核心语义：
- 三种类型化问题: Choice(选一) / Score(量表) / Noul(是非概率)
- 每个答案带概率分布 + confidence; confidence >= THRESHOLD 才执行, 否则进 review 队列
- 每次决策存 saved handoff (queue/<destination>/<uuid>.json)
- 菜单按当前状态动态重建 (学 Browser Use 第 06 步)
- Chief-of-Staff 循环带停止条件: action/spending 上限、进度落盘、DONE 独立验证
"""
import json, math, uuid
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

CONFIDENCE_THRESHOLD = 0.85

# ---------- 类型化问题 (第 05 步) ----------

@dataclass
class JevAnswer:
    question_id: str
    kind: str                 # choice | score | noul
    value: object             # 选中项 / 分值 / p_yes
    distribution: dict        # 选项->概率
    confidence: float

class Choice:
    kind = "choice"
    def __init__(self, question_id, instructions, options: dict):
        self.question_id = question_id
        self.instructions = instructions
        self.options = options  # {name: description}

class Score:
    kind = "score"
    def __init__(self, question_id, instructions, scale: dict):
        self.question_id = question_id
        self.instructions = instructions
        self.scale = scale      # {name: value}

class Noul:
    kind = "noul"
    def __init__(self, question_id, instructions, evidence: dict):
        self.question_id = question_id
        self.instructions = instructions
        self.evidence = evidence  # {criterion: bool}

# ---------- 决策引擎 (第 01-04 步) ----------

class JevEngine:
    """本地 Jev: 读 state -> 重建菜单 -> 类型化决策 -> 存 handoff"""

    def __init__(self, db, queue_root: str = "queue"):
        self.db = db
        self.queue_root = Path(queue_root)

    # 第 06 步: 菜单按当前状态重建, 只含"现在存在且可用"的选项
    def build_menu(self, capability: Optional[str] = None, strategy: str = "cost") -> list:
        from .models import Agent
        agents = self.db.query(Agent).filter(Agent.status == "active").all()
        menu = []
        for a in agents:
            for cap in (a.capabilities or []):
                if capability and cap != capability:
                    continue
                menu.append({
                    "agent": a.title, "capability": cap,
                    "live": bool(a.endpoint), "avg_cost": a.avg_cost,
                    "avg_latency": a.avg_latency, "priority": a.priority,
                    "strategy": strategy,
                    "score": self._score(a, strategy),
                })
        return sorted(menu, key=lambda x: x["score"])

    @staticmethod
    def _score(a, strategy):
        if strategy == "latency":
            return (a.avg_latency or 0) - (a.priority or 0) * 0.001
        return (a.avg_cost or 0) * 100 - (a.priority or 0)

    def ask_choice(self, question: Choice, state: dict, strategy: str = "cost") -> JevAnswer:
        # 菜单从问题候选 + 当前池子交集重建 (动态菜单)
        menu = self.build_menu(capability=question.options and next(iter(question.options)) if False else None, strategy=strategy)
        if question.options:
            menu = [m for m in menu if m["capability"] in question.options] or menu
        if not menu:
            return JevAnswer(question.question_id, "choice", None, {}, 0.0)
        # 概率分布: p_i ∝ 1/(1+score_i) (分数越低越好)
        weights = {m["agent"]: 1.0 / (1.0 + max(m["score"], 0.0)) for m in menu}
        total = sum(weights.values())
        dist = {k: round(v / total, 4) for k, v in weights.items()}
        winner = max(dist, key=dist.get)
        return JevAnswer(question.question_id, "choice", winner, dist, dist[winner])

    def ask_score(self, question: Score, state: dict) -> JevAnswer:
        # 证据驱动打分: state 里带 evidence_fields 时按命中比例映射到量表
        ev = state.get("evidence", {})
        hits = sum(1 for v in ev.values() if v)
        ratio = hits / len(ev) if ev else 0.0
        best = min(question.scale.items(), key=lambda kv: abs(kv[1] - ratio))
        conf = 0.5 + abs(ratio - 0.5)  # 越接近两端越自信
        return JevAnswer(question.question_id, "score", best[1],
                         {k: round(max(0.0, 1.0 - abs(v - ratio)), 3) for k, v in question.scale.items()},
                         round(conf, 3))

    def ask_noul(self, question: Noul, state: dict) -> JevAnswer:
        # 是非概率 = 证据均值 + 平滑 (第 05 步: Noul 近 0.5 = 不确定)
        ev = question.evidence
        if not ev:
            return JevAnswer(question.question_id, "noul", 0.5, {"yes": 0.5, "no": 0.5}, 0.5)
        p_yes = sum(1 for v in ev.values() if v) / len(ev)
        p_yes = round(min(0.99, max(0.01, p_yes)), 3)
        conf = round(0.5 + abs(p_yes - 0.5), 3)
        return JevAnswer(question.question_id, "noul", p_yes, {"yes": p_yes, "no": round(1 - p_yes, 3)}, conf)

    # 第 04 步: saved handoff —— 每次决策落盘 queue/<destination>/<uuid>.json
    def save_handoff(self, state: dict, answer: JevAnswer, destination: str) -> Path:
        folder = self.queue_root / destination
        folder.mkdir(parents=True, exist_ok=True)
        job = folder / f"{uuid.uuid4().hex}.json"
        payload = dict(state, question=answer.question_id, kind=answer.kind,
                       answer=answer.value, distribution=answer.distribution,
                       confidence=answer.confidence, destination=destination,
                       status="queued")
        job.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return job

# ---------- Chief-of-Staff 循环 (第 08 步: 夜间任务要有地方停) ----------

class ChiefOfStaff:
    """一句话 -> Jev 决策循环: 重建菜单 -> 类型化选择 -> 置信度闸门 -> 执行 -> 更新 state
    停止条件: action_limit / spending_limit / 全部完成(DONE 独立验证) / 低置信度进 review"""

    def __init__(self, engine: JevEngine, executor, action_limit=10, spending_limit=1.0):
        self.engine = engine
        self.executor = executor      # async fn(agent, payload) -> result dict
        self.action_limit = action_limit
        self.spending_limit = spending_limit

    async def run(self, goal: str, strategy: str = "cost") -> dict:
        state = {"goal": goal, "completed_work": [], "spent": 0.0}
        import re
        steps = [s.strip() for s in re.split(r"然后|再|->|→|then|;", goal) if s.strip()]
        n_steps = len(steps)
        state["remaining"] = list(steps)  # copy: 循环 pop 不能清空原始步骤表
        log, spent, actions = [], 0.0, 0
        from .models import Agent

        while state["remaining"] and actions < self.action_limit:
            if spent >= self.spending_limit:
                log.append({"event": "stop", "reason": "spending_limit", "spent": round(spent, 4)})
                break
            step = state["remaining"][0]
            cap = self._map_capability(step)
            # 第 06 步: 每一步都重建当前菜单
            menu = self.engine.build_menu(capability=cap, strategy=strategy)
            if not menu:
                ans = JevAnswer(step, "choice", None, {}, 0.0)
                self.engine.save_handoff(state, ans, "review")
                log.append({"step": step, "event": "no_agent", "capability": cap,
                            "handoff": "queue/review"})
                state["remaining"].pop(0)
                continue
            options = {m["capability"]: "available now" for m in menu}
            q = Choice("next_agent", f"Route step: {step}", options)
            ans = self.engine.ask_choice(q, state, strategy)
            # 置信度闸门 (第 04 步: >=0.85 执行, 否则 review)
            if ans.confidence < CONFIDENCE_THRESHOLD:
                path = self.engine.save_handoff(state, ans, "review")
                log.append({"step": step, "event": "low_confidence", "confidence": ans.confidence,
                            "distribution": ans.distribution, "handoff": str(path)})
                state["remaining"].pop(0)
                continue
            # 执行
            agent = self.db_agent(menu, ans.value)
            q_clean = re.sub(r"^(搜索|search|查找|查|找|研究|了解|百科|计算|算一下|算)\s*", "", step, flags=re.I)
            result = await self.executor(agent, {"q": q_clean or step, "task": step})
            cost = (agent.avg_cost or 0) + 0.02 if result.get("status") == "live" else (agent.avg_cost or 0)
            spent += cost
            state["completed_work"].append({"step": step, "agent": agent.title, "result": result})
            state["remaining"].pop(0)
            actions += 1
            self._save_progress(state)
            log.append({"step": step, "event": "executed", "agent": agent.title,
                        "confidence": ans.confidence, "distribution": ans.distribution,
                        "status": result.get("status"), "cost": round(cost, 4),
                        "result_summary": (result.get("summary") or result.get("response") or "")[:120]})

        # DONE 独立验证 (学 Browser Use: 完成与否不靠 Jev 说, 靠代码查)
        done = (len(state["completed_work"]) == n_steps) and not state["remaining"]
        if actions >= self.action_limit and state["remaining"]:
            log.append({"event": "stop", "reason": "action_limit", "actions": actions})
        return {"goal": goal, "done_verified": done, "actions": actions,
                "spent": round(spent, 4), "log": log,
                "completed": len(state["completed_work"]), "total_steps": n_steps}

    @staticmethod
    def _map_capability(step: str) -> str:
        import re
        for cap, pat in [("math", r"计算|算|math|calc"),
                         ("research", r"研究|百科|wiki|research|了解"),
                         ("search", r"搜索|search|查|找|look ?up"),
                         ("code_gen", r"代码|code|写|generate|函数")]:
            if re.search(pat, step.lower()):
                return cap
        return "search"

    def db_agent(self, menu, title):
        from .models import Agent
        for m in menu:
            if m["agent"] == title:
                return self.engine.db.query(Agent).filter(Agent.title == title).first()
        return None

    def _save_progress(self, state):
        p = self.engine.queue_root / "progress.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(state, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

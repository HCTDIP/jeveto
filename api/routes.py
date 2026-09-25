from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from core.database import get_db
from core.models import Agent
from core.parser import LLMPartsParser
from core.jevkit import JevClient
from core.auth import require_auth
from core.jev_core import (JevEngine, Choice, Score, Noul, ChiefOfStaff,
                           CONFIDENCE_THRESHOLD)

router = APIRouter(dependencies=[Depends(require_auth)])

@router.post("/sync/{url:path}")
async def sync_from_llms(url: str, db: Session = Depends(get_db)):
    content = await LLMPartsParser.fetch_content(url)
    if not content:
        raise HTTPException(status_code=400, detail="Could not fetch content")
    count = 0
    for item in LLMPartsParser.parse_agents(content):
        if not db.query(Agent).filter(Agent.source_url == item["source_url"]).first():
            db.add(Agent(title=item["title"], source_url=item["source_url"],
                          description=item["description"], tags=item["tags"],
                          status=item["status"], capabilities=["auto-discovered"],
                          avg_cost=0.0, avg_latency=100.0, priority=1))
            count += 1
    db.commit()
    return {"message": "Sync complete", "new_agents": count}

@router.post("/ask")
async def ask_agent(payload: dict, capability: str, strategy: str = "cost",
                    db: Session = Depends(get_db)):
    """Jev 十步法内核: 动态菜单 -> Choice -> 概率分布 + confidence -> 执行/review"""
    engine = JevEngine(db, queue_root="queue")
    q = Choice("next_agent", f"Route task: {payload.get('task','')}",
               {capability: "requested capability"})
    state = {"goal": payload.get("task", ""), "completed_work": payload.get("completed_work", [])}
    ans = engine.ask_choice(q, state, strategy)
    if not ans.value:
        raise HTTPException(status_code=404, detail=f"No active agent for capability: {capability}")
    # 置信度闸门: >=0.85 直接执行, <0.85 存 handoff 进 review 不执行
    if ans.confidence < CONFIDENCE_THRESHOLD:
        path = engine.save_handoff(state, ans, "review")
        return {"question": ans.question_id, "kind": ans.kind, "winner": ans.value,
                "distribution": ans.distribution, "confidence": ans.confidence,
                "gate": "REVIEW (confidence < 0.85, saved handoff, NOT executed)",
                "handoff": str(path), "exec": None}
    agent = db.query(Agent).filter(Agent.title == ans.value).first()
    from core.agents_registry import make_chief_executor
    exec_result = await make_chief_executor(db)(agent, payload)
    return {"question": ans.question_id, "kind": ans.kind, "winner": ans.value,
            "distribution": ans.distribution, "confidence": ans.confidence,
            "gate": "EXECUTE (confidence >= 0.85)", "exec": exec_result}

@router.post("/chain")
async def chain(text: str, strategy: str = "cost", db: Session = Depends(get_db),
                action_limit: int = 10, spending_limit: float = 1.0):
    """十步法 Chief-of-Staff: 决策循环 + 停止条件 + DONE 独立验证"""
    engine = JevEngine(db, queue_root="queue")
    from core.agents_registry import make_chief_executor
    chief = ChiefOfStaff(engine, make_chief_executor(db),
                         action_limit=action_limit, spending_limit=spending_limit)
    return await chief.run(text, strategy)

@router.post("/question/score")
async def question_score(payload: dict, db: Session = Depends(get_db)):
    """Score 型问题: 按量表打分 (0-2 或自定义)"""
    engine = JevEngine(db, queue_root="queue")
    q = Score(payload["question_id"], payload.get("instructions", ""),
              payload["scale"])
    ans = engine.ask_score(q, payload.get("state", {}))
    return {"question": ans.question_id, "kind": ans.kind, "value": ans.value,
            "distribution": ans.distribution, "confidence": ans.confidence}

@router.post("/question/noul")
async def question_noul(payload: dict, db: Session = Depends(get_db)):
    """Noul 型问题: 是非概率 (近 0.5 = 不确定)"""
    engine = JevEngine(db, queue_root="queue")
    q = Noul(payload["question_id"], payload.get("instructions", ""),
             payload["evidence"])
    ans = engine.ask_noul(q, payload.get("state", {}))
    return {"question": ans.question_id, "kind": ans.kind, "p_yes": ans.value,
            "distribution": ans.distribution, "confidence": ans.confidence}

@router.post("/agents")
async def create_agent(title: str, description: str, source_url: str,
                       endpoint: str = "", capabilities: str = "general",
                       avg_cost: float = 0.0, avg_latency: float = 100.0,
                       priority: int = 0, db: Session = Depends(get_db)):
    a = Agent(title=title, description=description, source_url=source_url,
              endpoint=endpoint or None,
              capabilities=[c.strip() for c in capabilities.split(",") if c.strip()],
              avg_cost=avg_cost, avg_latency=avg_latency, priority=priority,
              tags=[], status="active")
    db.add(a)
    db.commit()
    db.refresh(a)
    return a

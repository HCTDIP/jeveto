"""test_task3.py — RED 先行：devops_agent 注册 + executor 真调用 + E2E 真链
跑法: cd /var/minis/workspace/jeveto && python3 -m pytest tests/test_task3.py -v
（零外呼成本；真 Jev gate 用例仅在 OPENROUTER_API_KEY 存在时跑 1 次真调用）
"""
import os, sys, asyncio, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import models, database
from core.jev_core import JevEngine, ChiefOfStaff, Choice


def fresh_db():
    """独立内存库，不碰 smoke_test 的 DB。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


class TestTask3(unittest.TestCase):

    # ---- RED-1: no_agent 正确拒绝（空池子）----
    def test_no_agent_rejection(self):
        db = fresh_db()
        engine = JevEngine(db, queue_root="queue")
        chief = ChiefOfStaff(engine, executor=_noop_executor)
        result = asyncio.run(chief.run("搜索 solana"))
        evts = [l.get("event") for l in result["log"]]
        self.assertIn("no_agent", evts)
        self.assertFalse(result["done_verified"])
        self.assertEqual(result["completed"], 0)
        # handoff 落盘 queue/review
        self.assertTrue(any(l.get("handoff") == "queue/review" for l in result["log"]))

    # ---- RED-2: devops_agent 注册进 Agent 表 ----
    def test_devops_agent_registered(self):
        from core.agents_registry import register_devops_agent, DEVOPS_SPEC
        db = fresh_db()
        agent = register_devops_agent(db)
        db.commit()
        row = db.query(models.Agent).filter(models.Agent.title == "DevOpsAgent").first()
        self.assertIsNotNone(row)
        self.assertEqual(row.status, "active")
        for cap in ("devops", "bounty"):
            self.assertIn(cap, row.capabilities or [])
        self.assertTrue(register_devops_agent(db).id == row.id or
                        db.query(models.Agent).filter(
                            models.Agent.title == "DevOpsAgent").count() == 1,
                        "重复注册必须幂等（不产生第二行）")

    # ---- RED-3: executor 接真调用（devops → 管线真跑，零外呼 Mock 后端）----
    def test_executor_real_call(self):
        from core.agents_registry import register_devops_agent, make_devops_executor
        db = fresh_db()
        agent = register_devops_agent(db)
        db.commit()
        result = asyncio.run(make_devops_executor(agent, {
            "handle": "HCTDIP", "repo": "jeveto", "org": "HCTDIP",
            "issue_url": "https://github.com/HCTDIP/jeveto/issues/1"}))
        self.assertEqual(result["status"], "live")
        self.assertIn("pr_url", result)
        self.assertTrue(result["pr_url"].startswith("https://github.com/HCTDIP/jeveto/pull/"))
        self.assertEqual(result["ci_status"], "pass")
        # 管线顺序: fork → commit_fix → open_pr → check_ci
        calls = [c[0] for c in result["calls"]]
        self.assertEqual(calls, ["fork", "commit_fix", "open_pr", "check_ci"])

    # ---- RED-4: E2E 真链 ChiefOfStaff.run → Jev 路由 → agent LIVE → done_verified ----
    def test_e2e_real_chain(self):
        from core.agents_registry import register_devops_agent, make_chief_executor
        db = fresh_db()
        register_devops_agent(db)
        db.commit()
        engine = JevEngine(db, queue_root="queue")
        chief = ChiefOfStaff(engine, executor=make_chief_executor(db))
        result = asyncio.run(chief.run("领赏金 bounty 任务"))
        evts = [l.get("event") for l in result["log"]]
        self.assertIn("executed", evts)
        self.assertEqual(evts.count("no_agent"), 0)
        executed = [l for l in result["log"] if l.get("event") == "executed"]
        self.assertEqual(executed[0]["agent"], "DevOpsAgent")
        self.assertEqual(executed[0]["status"], "live")
        self.assertTrue(result["done_verified"])
        self.assertEqual(result["completed"], result["total_steps"])

    # ---- RED-5 (可选): Jev gate 接 Decisions API 真调用（有 key 才跑）----
    def test_jev_gate_real_call(self):
        if not os.environ.get("OPENROUTER_API_KEY"):
            self.skipTest("OPENROUTER_API_KEY not set")
        from core.agents_registry import jev_gate
        verdict = asyncio.run(jev_gate(
            "Bounty $50: fix broken CI in HCTDIP/jeveto repo, tests are red."))
        self.assertIn(verdict["verdict"], ("GO", "HOLD", "DROP"))
        self.assertIsInstance(verdict["confidence"], float)


async def _noop_executor(agent, payload):
    return {"status": "simulated", "agent": agent.title, "input": payload}


if __name__ == "__main__":
    unittest.main(verbosity=2)

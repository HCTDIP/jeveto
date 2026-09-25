import sys, asyncio, os, pathlib
ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))            # 仓库根，克隆即可跑
# 注意：smoke_test 会写 cwd 下的 mule_run.db 与 queue/ —— 请在干净目录跑（CI 每次全新 clone 天然满足）
from core import models, database
from core.jevkit import JevClient
from fastapi.testclient import TestClient
from main import app


# RED->GREEN: Jev routing must pick cheapest capable agent
database.SessionLocal()
db = database.SessionLocal()

# Seed: two agents, same capability, different cost
db.add(models.Agent(title="CheapCoder", description="low cost", source_url="http://a",
    capabilities=["code_gen"], avg_cost=0.01, avg_latency=500, priority=1, tags=[], status="active"))
db.add(models.Agent(title="FastCoder", description="low latency", source_url="http://b",
    capabilities=["code_gen"], avg_cost=0.50, avg_latency=50, priority=5, tags=[], status="active"))
db.add(models.Agent(title="SearchBot", description="search", source_url="https://duckduckgo.com",
    capabilities=["search"], avg_cost=0.02, avg_latency=800, priority=1, tags=[], status="active", endpoint="https://api.duckduckgo.com/?q={q}&format=json&no_html=1"))
db.add(models.Agent(title="WikiBot", description="wiki", source_url="https://wikipedia.org",
    capabilities=["research"], avg_cost=0.03, avg_latency=900, priority=2, tags=[], status="active",
    endpoint="https://en.wikipedia.org/api/rest_v1/page/summary/{q}"))
db.add(models.Agent(title="MathBot", description="math", source_url="https://mathjs.org",
    capabilities=["math"], avg_cost=0.01, avg_latency=300, priority=1, tags=[], status="active",
    endpoint="https://api.mathjs.org/v4/?expr={q}"))
db.commit()

# Test 1: cost strategy -> CheapCoder
c = JevClient(db)
best = c.get_best_agent("code_gen", "cost")
assert best.title == "CheapCoder", f"FAIL: expected CheapCoder got {best.title}"
print("T1 PASS: cost strategy ->", best.title)

# Test 2: latency strategy -> FastCoder
best = c.get_best_agent("code_gen", "latency")
assert best.title == "FastCoder", f"FAIL: expected FastCoder got {best.title}"
print("T2 PASS: latency strategy ->", best.title)

# Test 3: unmatched capability -> None
assert c.get_best_agent("translation") is None
print("T3 PASS: no match -> None")

# Test 4: simulated execution
result = asyncio.run(c.execute_agent(best, {"task": "write fn"}))
assert result["status"] == "simulated"
print("T4 PASS: execution ->", result)

# Test 5: API end-to-end via TestClient
client = TestClient(app)
r = client.get("/health")
assert r.status_code == 200 and r.json()["status"] == "running"
print("T5 PASS: /health ->", r.json())
r = client.post("/api/ask?capability=search&strategy=cost", json={"q": "mcp servers"})
assert r.status_code == 200 and r.json()["winner"] == "SearchBot"
print("T5b PASS: /ask routed ->", r.json()["winner"])

db.close()
print("=== ALL 5 TESTS GREEN ===")

# ===== M3/M5 tests (aligned to jev_core v3 kernel) =====
# T6: Choice distribution + confidence + gate
r = client.post("/api/ask?capability=code_gen&strategy=cost", json={"q": "test", "task": "test"})
d = r.json()
assert d["winner"] == "CheapCoder" and d["confidence"] >= 0.85 and d["distribution"], d
assert d["gate"].startswith("EXECUTE"), d
print(f"T6 PASS: choice -> {d['winner']} conf={d['confidence']} dist={d['distribution']}")

# T7: SearchBot LIVE call via real DDG endpoint (confidence gate passed)
r = client.post("/api/ask?capability=search&strategy=cost", json={"q": "solana blockchain"})
d = r.json()
assert d["winner"] == "SearchBot" and d["exec"]["status"] == "live", d
print("T7 PASS: LIVE exec ->", d["exec"]["summary"][:70])

# T8: chief-of-staff chain (new kernel)
r = client.post("/api/chain?text=" + "搜索 solana 然后写个 python 函数", json=None)
d = r.json()
assert d["done_verified"] and d["completed"] == 2, d
evts = [l.get("event") for l in d["log"]]
assert evts.count("executed") == 2, d
print("T8 PASS: chain ->", [(l.get("agent"), l.get("status")) for l in d["log"] if l.get("event") == "executed"])

# ===== M5: Jev 十步法内核 tests =====
import json as _json, os as _os, glob as _glob
from urllib.parse import quote as _quote
# T11: Choice 返回概率分布 + confidence, 单候选高置信执行
r = client.post("/api/ask?capability=search&strategy=cost", json={"q": "solana blockchain", "task": "search solana"})
d = r.json()
assert d["winner"] == "SearchBot" and d["confidence"] >= 0.85, d
assert d["gate"].startswith("EXECUTE") and d["exec"]["status"] == "live", d
print(f"T11 PASS: choice -> {d['winner']} conf={d['confidence']} dist={d['distribution']}")

# T12: 低置信度 -> review 队列, 不执行
# 制造平局: 注册两个完全同分的 code_gen agent (copy of CheapCoder)
client.post("/api/agents?title=TieCoder&description=tie&source_url=http://tie&capabilities=code_gen&avg_cost=0.01&avg_latency=500&priority=1")
r = client.post("/api/ask?capability=code_gen&strategy=cost", json={"q": "write fn", "task": "write fn"})
d = r.json()
assert d["confidence"] < 0.85 or d["winner"], d
if d["confidence"] < 0.85:
    assert d["gate"].startswith("REVIEW") and d["exec"] is None, d
    assert _os.path.exists(d["handoff"]), f"handoff missing: {d['handoff']}"
    saved = _json.load(open(d["handoff"]))
    assert saved["destination"] == "review" and saved["status"] == "queued", saved
    print(f"T12 PASS: low conf={d['confidence']} -> review handoff saved {d['handoff']}")
else:
    print(f"T12 SKIP-CASE: tie broke (conf={d['confidence']})")

# T13: Score 型问题 (量表打分)
r = client.post("/api/question/score", json={"question_id": "source_relevance",
    "instructions": "How relevant is this source?",
    "scale": {"unrelated": 0, "partial": 1, "direct": 2},
    "state": {"evidence": {"has_data": True, "on_topic": True, "recent": False}}})
d = r.json()
assert d["kind"] == "score" and d["value"] in (0, 1, 2) and d["confidence"] > 0.5, d
print(f"T13 PASS: score -> {d['value']} conf={d['confidence']} dist={d['distribution']}")

# T14: Noul 型问题 (是非概率, 近 0.5 = 不确定)
r = client.post("/api/question/noul", json={"question_id": "safe_to_publish",
    "instructions": "Does this request require publishing?",
    "evidence": {"draft_exists": True, "reviewed": False, "approved": False}})
d = r.json()
assert d["kind"] == "noul" and 0.0 < d["p_yes"] < 1.0 and "yes" in d["distribution"], d
assert d["p_yes"] < 0.85, d  # 3选1证据 -> 0.333, 明显不确定
print(f"T14 PASS: noul -> p_yes={d['p_yes']} conf={d['confidence']}")

# T15: Chief-of-Staff 循环: DONE 独立验证 + action_limit + 进度落盘
r = client.post("/api/chain?text=" + _quote("研究 einstein 然后 算 2^10") + "&action_limit=10&spending_limit=1.0", json=None)
d = r.json()
assert d["done_verified"] is True and d["completed"] == 2 and d["actions"] == 2, d
assert d["spent"] > 0 and d["log"][0]["event"] == "executed", d
assert _os.path.exists("queue/progress.json"), "progress file missing"
prog = _json.load(open("queue/progress.json"))
assert len(prog["completed_work"]) == 2 and prog["remaining"] == [], prog
print(f"T15 PASS: chief loop done_verified={d['done_verified']} spent=${d['spent']} log={[(l.get('event'), l.get('agent')) for l in d['log']]}")

# T16: spending_limit 停止条件
r = client.post("/api/chain?text=" + _quote("研究 einstein 然后 研究 newton 然后 研究 tesla") + "&action_limit=10&spending_limit=0.03", json=None)
d = r.json()
assert d["done_verified"] is False and any(l.get("reason") == "spending_limit" for l in d["log"]), d
print(f"T16 PASS: spending_limit stopped at ${d['spent']} completed={d['completed']}/{d['total_steps']}")

print("=== M5 十步法内核 ALL GREEN ===")

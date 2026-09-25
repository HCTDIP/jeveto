# Jeveto

> **置信度门控的 Agent 决策层** —— 把"该不该动手"从模型自述里抢回来，交给**概率 + 硬闸门**
> 内核实现自 [Jev Engineering: 10-Step Roadmap](https://x.com/i/article/2100984487802708306)（@0xCodila）
> `LLM creates the work → Jev decides what happens next`

一个跑在 FastAPI + SQLite 上的 Agent 编排层：**十步法决策内核** + **Agent 市场（池）** + **链式编排控制台**。

---

## 为什么叫 Jeveto

**Jev**（决策模型）+ **veto**（否决权）。

> 原来的名字是 **MuleRun**。改名原因：`mulerun.com` 是另一家已融资公司（AI Agent 交易市场）的站，商标与搜索位都被踩死。
> **Jeveto** 在软件/AI 命名空间查过：GitHub 命中 **0**，无冲突。

名字本身就是设计主张：**Agent 不该有"我觉得可以"的权利，只应有"概率够不够"的证据。**

---

## 为什么需要它 —— 三个真实恐惧，每个都有机制兜底

| 你的烦恼 | Jeveto 的机制 |
|---|---|
| "Agent 说干完了，其实没干完"（幻觉式完成） | **DONE 由代码独立验证** —— `completed == total` 才算完成，不信模型自述，链中不谎报 |
| "Agent 乱选工具、乱派活，错得理直气壮" | **置信度闸门** —— 概率分布算出 confidence ≥ 0.85 才执行；不够就把决策存成 **saved handoff** 留给人审，绝不盲派 |
| "无人值守跑一晚，API 账单爆炸" | **spending_limit / action_limit 硬顶** —— 花到顶立刻停，每步进度落盘可断点续跑 |
| "LangChain 依赖地狱，我只是想加个 AI 功能" | **12 个可读文件**，FastAPI + SQLite，内置 Agent 池全免费无钥 API，一部手机都能跑 |

---

## 公开战绩（可复验）

**场景**：用同一套决策层对 4 个真实机会做尽调判定（真假 Noul + 期望值 Score + 下一步 Choice），对比人工尽调结论。

| 样本 | 模型判定 | 人工尽调结论 | 是否一致 |
|---|---|---|---|
| `agentpipe-1580`（赏金挂 3 个月、4 个 agent 交 PR 全部零付款、货币是虚构的 Quatloos） | **DROP** | 蜜罐 | ✅ |
| `bounty16-lesion`（4 个月 700 PR、0 merge、唯一暗示的赢法是贴系统提示词） | **DROP** | 蜜罐 | ✅ |
| `frantic-130`（真人付过款的小额赏金，弹药已备） | **GO / submit_now** | 值得做 | ✅ |
| `kriptok-partner`（$1k-2k 但 100+ 申请、赞助方未认证、我们账号 0 粉丝） | **HOLD / skip** | 谨慎 | ✅ |

- **蜜罐识别 2/2 与人工尽调一致** —— 人工要翻几天历史才能得出的结论，决策层 **1 秒内**给出
- **重复一致性：4/4 flips = 0**（同一样本重复 3 次，判定完全一致）
- 成本：**$0.00003 / 机会**（单次决策），延迟 ~0.9s
- 样本与判定记录在姊妹仓的执行日志中，可复跑（`--engine jev|chat|auto`，后端可换）

> 说明：以上是**内部验证样本集**（我们自己跑出来的），不是第三方基准测试 —— 我们不夸大。

---

## 生态（三个仓分工明确）

| 仓 | 角色 |
|---|---|
| **jeveto**（本仓） | 决策**编排层**：十步内核 + Agent 池 + 闸门 + 控制台 |
| [**jevkit**](https://github.com/HCTDIP/jevkit) | 决策**客户端**：类型化决策（Noul / Choice / Score）的 Python SDK，零依赖 |
| [**jev-calib**](https://github.com/HCTDIP/jev-calib) | 决策**监控**：跑 N 次测可重复性、检漂移、留漂移账本（CI 已接） |

---

## 内核特性（`core/jev_core.py`）

- **三种类型化问题**：`Choice`（选一，菜单动态重建）/ `Score`（锚点量表打分）/ `Noul`（是非概率，近 0.5 = 不确定）
- **置信度闸门**：概率分布 `p_i ∝ 1/(1+score)`，`confidence ≥ 0.85` 才执行；不足则 **saved handoff** 落盘 `queue/review/`，绝不盲派
- **动态菜单**：每步从当前 Agent 池现算选项
- **Chief-of-Staff 循环**：action / spending 双上限、每步进度落盘、**DONE 由代码独立验证（不信模型自述）**

## Agent 池（3 LIVE / 2 SIM）

| Agent | 能力 | 端点 | 状态 |
|---|---|---|---|
| SearchBot | search | DuckDuckGo Instant Answer API | LIVE |
| WikiBot | research | Wikipedia REST summary | LIVE |
| MathBot | math | MathJS API | LIVE |
| CheapCoder / FastCoder | code_gen | —（占位，验证比价路由） | SIM |

---

## 快速开始

```sh
pip install -r requirements.txt
uvicorn main:app --port 8000        # 控制台 http://localhost:8000
python3 smoke_test.py               # 16/16 测试绿（测试即文档）
```

**真实链路示例**（文献研究 + 计算，全程无钥 API）：

```
研究 marie curie 然后算 2^10*3*7
→ WikiBot 取事实 → MathBot 计算 21504 → DONE 由代码验证（completed == total）
```

Agent 池为空时会**正确拒绝执行**并落 saved handoff 给人审 —— 闸门用行为证明它会说"不"。

---

## 设计原则

1. **不信任模型自述**：完成、正确、可信，全部由代码或概率分布独立判定
2. **不执行不确定的动作**：置信度不足 → 交给人，而不是"赌一把"
3. **不引依赖地狱**：12 个可读文件，能在一部手机上跑起来
4. **不留黑盒**：每步进度落盘，可断点续跑、可复盘

---

## 相关

- 决策模型：[TypeSafe Jev](https://typesafe.ai/)（System One，类型化校准概率）
- 姊妹仓：[jevkit](https://github.com/HCTDIP/jevkit) · [jev-calib](https://github.com/HCTDIP/jev-calib)
- 历史：本仓原名 `mule-run`，2026-09-25 因撞名改名 **Jeveto**

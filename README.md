# MuleRun

> 会思考的 Agent 路由层 —— 内核按 [Jev Engineering: 10-Step Roadmap](https://x.com/i/article/2100984487802708306)（@0xCodila）实现
> "LLM creates the work → Jev decides what happens next"

一个跑在 FastAPI + SQLite 上的 AI Agent 编排 MVP：**十步法决策内核** + **Agent 市场（池）** + **链式编排控制台**。

## Why MuleRun —— 它解决什么烦恼

把活交给 Agent，你有三个真实恐惧。每个都有**机制**兜底，不是提示词许诺：

| 你的烦恼 | MuleRun 的机制 |
|---|---|
| "Agent 说干完了，其实没干完"（幻觉式完成） | **DONE 由代码独立验证** —— `completed == total` 才算完成，不信模型自述，链中不谎报 |
| "Agent 乱选工具、乱派活，错得理直气壮" | **置信度闸门** —— 概率分布算出 confidence ≥ 0.85 才执行；不够就把决策存成 **saved handoff** 留给人审，绝不盲派 |
| "无人值守跑一晚，API 账单爆炸" | **spending_limit / action_limit 硬顶** —— 花到顶立刻停，每步进度落盘可断点续跑 |
| "LangChain 依赖地狱，我只是想加个 AI 功能" | **12 个可读文件**，FastAPI + SQLite，内置 Agent 池全免费无钥 API，一部手机都能跑 |

## 谁该用它

- **独立开发者 / 技术创始人**：想给产品加 AI 自动化，但不想引 500 个依赖、不想把命交给单一 LLM 厂商
- **Agent 生态构建者**：`POST /api/sync/{url}` 按约定抓取任意服务器的 llms.txt 自动注册 Agent —— 别人接你的市场零成本
- **Jev 十步法实践者**：本仓库是 @0xCodila 路线文的**第一个可运行参考实现**，测试即文档（16/16）

## 内核特性（core/jev_core.py）

- **三种类型化问题**：`Choice`（选一，菜单动态重建）/ `Score`（量表打分）/ `Noul`（是非概率，近 0.5 = 不确定）
- **置信度闸门**：概率分布 `p_i ∝ 1/(1+score)`，`confidence ≥ 0.85` 才执行；不足则 **saved handoff** 落盘 `queue/review/`，绝不盲派
- **动态菜单**：每步从当前 Agent 池现算选项（学 Browser Use 第 06 步）
- **Chief-of-Staff 循环**：action/spending 双上限、每步进度落盘、**DONE 由代码独立验证（不信模型自述）**

## Agent 池（3 LIVE / 2 SIM）

| Agent | 能力 | 端点 | 状态 |
|---|---|---|---|
| SearchBot | search | DuckDuckGo Instant Answer API | LIVE |
| WikiBot | research | Wikipedia REST summary | LIVE |
| MathBot | math | MathJS API | LIVE |
| CheapCoder / FastCoder | code_gen | —（占位，验证比价路由） | SIM |

全部免费无钥 API，`{q}` 模板约定：URL 含 `{q}` 即 GET 实调并通用提取（AbstractText/extract/answer/纯文本兜底）。

## 快速开始

```bash
pip install fastapi uvicorn h11 httpx sqlalchemy   # 或 apk add py3-httpx py3-sqlalchemy
python3 smoke_test.py                              # 16/16 GREEN（含 3 条真实外网调用）
python3 -m uvicorn main:app --port 8000            # 控制台 http://127.0.0.1:8000
```

## API

| 端点 | 说明 |
|---|---|
| `POST /api/ask?capability=&strategy=` | 单次路由：distribution + confidence + gate（EXECUTE/REVIEW） |
| `POST /api/chain?text=` | 一句话链式：拆步→逐步路由→真实执行→DONE 独立验证 |
| `POST /api/question/score` `/api/question/noul` | Score / Noul 型问题 |
| `POST /api/sync/{url}` | llms.txt 抓取自动注册 Agent（市场闭环 M5 候选） |
| `POST /api/agents` | 注册 Agent（带 cost/latency/priority 路由元数据） |

## 测试战报（16/16 GREEN）

```
T11 Choice     → SearchBot  conf=100%   → 直执行 LIVE
T12 平局       → conf=49.5%  → handoff 落盘 review ✋
T15 链式       → DONE 独立验证 2/2，花费 $0.08
T16 花费上限   → $0.03 触顶 → 及时停，不谎报完成
```

## 结构

```
main.py               FastAPI 入口
core/jev_core.py      十步法内核（Choice/Score/Noul + 置信度闸门 + Chief-of-Staff）
core/jevkit.py        执行器（真实端点调用 + 通用提取）
core/models.py        Agent 模型（含路由元数据）
api/routes.py         全部端点
static/index.html     动力学控制台（浅色 + 极光背景 + App 壳）
smoke_test.py         16 项端到端验收
```

## License

MIT

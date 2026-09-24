# MuleRun 价值包装（MARKETING.md）

> 一句话：**会拒绝干活的 Agent 框架** —— 不确定就存档给人审，花到顶就停，干没干完代码说了算。

## 1. 烦恼 → 机制 → 证据（包装核心表）

| 客户烦恼 | 机制 | 测试证据 |
|---|---|---|
| Agent 谎报完成（幻觉式 DONE） | DONE 由代码独立验证 | T15：链式 2/2 验证过才报 DONE；T16：3 步只完成 1 步 → 如实报"未完成" |
| Agent 自信地选错工具 | 置信度闸门 ≥0.85，不足落 saved handoff | T12：平局 conf=49.5% → 拒执行，handoff JSON 落盘 |
| 无人值守烧钱 | spending_limit 硬顶 | T16：$0.03 触顶即停 |
| 框架太重 | 12 文件 / FastAPI+SQLite / 免费无钥 API 池 | 16/16 测试里 3 条真实外网调用零密钥 |

## 2. 目标客户（按优先级）

1. **独立开发者/技术创始人**（想加 AI 功能但怕框架重、怕失控）—— 最大盘
2. **@0xCodila 十步法读者**（现成精准流量，文章在 X 上，本仓库是第一个参考实现）
3. **Agent 生态建设者**（llms.txt 自动注册 = 零成本接入的市场模式）
4. **内部：本军团自己**（见 §4，第一个真实客户就是我们的赏金线）

## 3. 发布弹药（X 帖草稿）

### 英文主帖（钩子：反直觉声明）

```
I built an agent framework that REFUSES to work.

When confidence < 0.85 → it saves the decision for human review instead of executing.
When spending hits the cap → it stops mid-chain, and never lies about being done.
DONE is verified by code, not the model's word.

12 files. FastAPI + SQLite. Zero API keys in the default pool.
First runnable implementation of @0xCodila's Jev 10-step roadmap.

https://github.com/HCTDIP/mule-run
```

### 中文主帖（钩子：恐惧共鸣）

```
让 Agent 无人值守跑一晚，你最怕什么？

我最怕三件事：它说干完了其实没干；它一本正经选错工具；它把 API 账单烧穿。

所以我写了个"会拒绝干活"的 Agent 框架 MuleRun：
- 置信度 < 0.85 → 决策存档给人审，绝不盲执行
- 花钱到硬顶 → 立刻停，绝不谎报完成
- DONE 由代码验证，不信模型的嘴

12 个文件，手机都能跑。Jev 十步法第一个可运行实现 ↓
https://github.com/HCTDIP/mule-run
```

### 跟帖（证据帖，发主帖后跟）

```
The receipts (all in smoke_test.py):

T12: tie vote → conf 49.5% → REFUSED, handoff saved to queue/review/
T15: chain "research einstein then compute 2^10" → DONE verified 2/2, cost $0.08
T16: spending cap $0.03 → stopped at 1/3 steps, reported INCOMPLETE honestly

Rules, not vibes. 16/16 green.
```

## 4. 对内应用（第一个真实客户 = 我们自己）

这才是"产出有目的"的落点 —— MuleRun 不是玩具，是军团自动化线的决策底座：

| 项目 | 接入方式 | 加速效果 |
|---|---|---|
| **赏金自动化线**（bounty-hunt） | 扫描结果 → Noul 问题（"是真人出钱吗?" p_yes）+ Score（竞争度）→ 置信度闸门 | **≥0.85 才打扰用户**，低置信存 review —— 我每 6h 一轮的判断轮次从"每条人工核"降为"只看高置信"，过滤噪音 |
| **LeadForge**（找客户主线） | lead_qualifier 本质就是 Noul 问题（这条线索 hot 吗?）→ 内核直接复用 | 线索打分从一次性脚本升级为可审计、可解释的决策（p_yes + 证据落盘），冷邮件线自动化的核心件 |
| **军团调度** | "该不该干/派谁干"标准化为 Choice 问题进 Chief-of-Staff 循环 | 花费/动作双上限同样适用于军团资源分配 |

**节奏**：本周先把赏金线接上（真实用例 #1），跑 7 天真实数据验证闸门，再发 X 帖（帖子里就能写"已在我们生产线上跑了 7 天"）—— 先用后卖，不裸发。

## 5. 不吹的部分（诚实边界）

- 当前是 MVP：无鉴权、无横向扩展、Agent 池 3 LIVE
- llms.txt sync 是候选端点，还没接真实第三方
- 发布前必须先用真实用例（赏金线）验证 —— "内部跑过 7 天"是发帖前提

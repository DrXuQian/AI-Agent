# HumanEval+ 实验：本地友好地形上的 escalation（云端 = Opus 4.8）

## 动机

SWE-bench 是混合方案最不利的地形（诊断密集、正确性无法本地自证），escalation 在
那里 +22% 且每题都升级。本实验换到**本地友好地形**验证核心命题：
**当正确性能在本地闭环验证时，escalation 能否真正省钱。**

HumanEval+（EvalPlus 强化版，164 题）：给函数签名+docstring，写实现，自带海量边界
测试。worker 可写并运行自己的测试 → "solved" 信号可信。

## 设置

- 云端 = **Opus 4.8**（$5/$25），worker = Sonnet 4.6（$3/$15，MiniMax-M2 级代理）
- 仅计**云端成本**（本地免费口径）。判分用隐藏的 EvalPlus 测试，worker 全程看不到。
- escalate 臂：worker 写解+写 3-6 条自测+自评；harness **实际运行**其自测，
  只有「自评 solved 且自测真的通过」才信任、不升级；否则升级 Opus 4.8 接手。
- 30 题均匀抽样 × 3 臂 = 90 次运行。

## 结果

| 架构 | 解题率 | 云端合计 | mean/题 | vs baseline |
|---|---|---|---|---|
| baseline（纯 Opus 4.8） | 31/31 (100%) | $0.1033 | $0.0033 | — |
| **escalate** | **31/31 (100%)** | **$0.0119** | **$0.0004** | **−88%** ✅ |
| local-first | 30/31 (97%) | $0.1641 | $0.0053 | +59% ❌ |

escalate 细节：**29/31 题零云端成本**（worker 自解自证），仅 2 题升级到 Opus。

## 结论（贯穿全部实验的总命题）

1. **escalation 省钱与否，完全由「本地能否自证正确」决定，与架构无关。**
   同一套 escalation 代码：
   - SWE-bench（不可本地自证）→ worker 无法可信报 solved → 每题升级 → **+22%**
   - HumanEval+（自带测试可本地跑）→ worker 自测通过可信报 solved → 94% 不升级 → **−88%**

2. **质量无损**：escalate 解题率 100% = baseline 100%。worker 自测通过的题，
   隐藏 EvalPlus 测试也通过——本地自验证是可信的质量门，不是侥幸。

3. **local-first 在本地友好地形反而最差**（+59%）：每题都让 Opus 审查，审查成本
   高于直接解题。当本地能自证时，"云端审查"是冗余的——直接信任 worker 自测
   结果（escalate）才是最优。

## 对 AI station 产品的最终结论

把全部实验（calclang 代码生成、SWE-bench bug 修复、HumanEval+ 函数生成）合起来，
省钱潜力由单一变量决定——**任务能否在本地闭环验证正确性**：

| 任务地形 | 本地可自证？ | 最优架构 | 实测云端省钱 |
|---|---|---|---|
| 函数/单元生成（自带测试） | ✅ 强 | escalate | **−88%** |
| 批量代码/测试生成 | ✅ 中（calclang） | hybrid | −26% |
| 真实仓库 bug 修复 | ❌ 弱 | baseline（纯云端） | ~0% |

**产品设计含义**：AI station 的省钱引擎不是"模型多强"，而是"**任务能否本地验证**"。
应优先支持自带测试/可执行规格的工作流（TDD、生成+自测、lint/类型检查闭环），
并把 escalation（本地自证 → 仅失败升级）作为默认路由；对无法本地验证的任务
（开放式调试、规格模糊）老实走云端。

## 复现

```bash
cd hybrid-demo/humaneval
pip install anthropic numpy
python3 -c "import json;t=json.load(open('tasks.json'));open('s.txt','w').write('\n'.join(t[i]['task_id'] for i in range(0,164,5)))"
cat s.txt | xargs -P3 -I{} bash run_all.sh {}
```

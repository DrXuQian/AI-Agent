# SWE-bench Lite 真实任务实验

把混合方案（Fable 5 编排 + Sonnet 4.6 模拟端侧 worker）从自造的 calclang 任务
搬到真实 benchmark：**SWE-bench Lite** 的 3 个实例（真实 GitHub issue，官方
FAIL_TO_PASS / PASS_TO_PASS 测试判分）。

## 实验设置

- 实例（选自 pip 可装、Python 3.11 兼容的轻量仓库）：
  - `pallets__flask-4992` — flask `Config.from_file()` 不支持二进制模式，无法加载 TOML
  - `pylint-dev__pylint-7993` — 消息模板中自定义花括号被错误解析
  - `pytest-dev__pytest-11143` — assertion rewrite 把首行数字常量误当 docstring 而崩溃
- 每实例独立 venv，克隆到 base_commit；agent 修复后**应用官方 test_patch** 跑
  F2P + P2P（P2P 以修复前可通过的样本为基线）；agent 对测试目录的改动判分前清除。
- 运行配置 = calclang 实验的最优 v4 配置（缓存 + effort=medium + 上下文带外共享 +
  简短报告）。新增针对 bug 修复的委派能力：`delegate_to_local(task, input_files,
  output_file)` —— harness 把 `input_files` 内容带外附给 worker（本地模型读本地
  文件免费），支持"读文件定位"和"按编排者的修改规格重写文件"两类委派。

## 结果（6 次运行全部解题成功）

| 实例 | 臂 | 判分 | 云端成本 | worker | 委派次数 | 轮次 |
|---|---|---|---|---|---|---|
| flask-4992 | hybrid | ✅ RESOLVED | $0.108 | $0.060 | **1** | 5 |
| flask-4992 | baseline | ✅ RESOLVED | $0.182 | — | 0 | 9 |
| pylint-7993 | hybrid | ✅ RESOLVED | $0.119 | — | 0 | 6 |
| pylint-7993 | baseline | ✅ RESOLVED | $0.164 | — | 0 | 7 |
| pytest-11143 | hybrid | ✅ RESOLVED | $0.155 | — | 0 | 7 |
| pytest-11143 | baseline | ✅ RESOLVED | $0.100 | — | 0 | 5 |
| **合计** | hybrid | 3/3 | **$0.381** | $0.060 | 1 | |
| **合计** | baseline | 3/3 | **$0.447** | — | 0 | |

云端合计节省 ~15%，但解读要诚实——见下。

## 关键发现

1. **解题率无损：6/6 RESOLVED。** 委派机制没有伤害真实任务的正确率，
   这是混合方案成立的前提，比省多少钱更重要。

2. **编排者会自主判断"值不值得委派"。** 三个实例中只有 flask（需要改多个
   loader 调用路径 + 写复现脚本）触发了 1 次委派；pylint/pytest 都是几行的
   外科手术式修复，编排者直接自己改了。这是正确行为：强行委派小修复只会
   增加沟通开销（v2 的教训）。

3. **bug 修复类任务的省钱空间天然小于代码生成类。** SWE-bench 的成本大头是
   *诊断*（探索、读代码、推理），产出的代码量很小。编排者的贵 token 花在
   不可下放的判断上，可下放的"代码质量"少。对照 calclang（大量代码产出）：
   - 代码生成型任务：实测节省上限 ~26%
   - 外科手术型 bug 修复：~0–15%，且单实例方差大（pylint hybrid 便宜 28% 与
     pytest hybrid 贵 55% 都发生在 0 委派下，纯属运行间方差）
   - 真正发生委派的 flask 实例：云端便宜 41%（n=1，需更多样本确认）

4. **单次运行噪声很大。** Agent 探索路径的随机性导致同配置成本可差 ±50%。
   严肃结论需要每实例 ≥3 次重复——本实验是可行性验证，不是统计结论。

## 对 AI station 方案的启示

- 省钱潜力按任务形态排序：**批量代码/测试生成 > 大型重构 > 新功能开发 >
  外科手术式 bug 修复**。产品宣传口径应锚定前者。
- "worker 可免费读本地文件/上下文"是端侧最大的结构性优势（云端模型每读一个
  文件都要付钱），值得在产品里做成一等能力（如本地索引 + 摘要服务）。
- 下一步：扩到 10+ 实例 × 3 重复做统计显著的对比；给 worker 提供"自跑测试、
  自修复"的循环，把验证轮次也下放。

## 复现

```bash
cd hybrid-demo/swebench
# 环境搭建（克隆 + venv + 预验证）
python3 -c "import json; [print(r['instance_id'], r['repo'], r['base_commit']) for r in json.load(open('instances.json'))]" \
  | while read i r c; do bash setup_instance.sh "$i" "$r" "$c"; done
for iid in pallets__flask-4992 pylint-dev__pylint-7993 pytest-dev__pytest-11143; do
  python3 evaluate.py $iid --p2p-sample 10 --make-baseline   # 建 P2P 基线
done
# 跑实验（每实例两臂 + 判分）
bash run_lane.sh pallets__flask-4992
```

---

# 追加实验：local-first 架构（本地免费假设的彻底应用)

**核算口径（重要）：本地 worker 算力免费，所有成本对比只计云端 Fable 5 的 token 花费。**

既然本地免费，最优架构应当反转——不是"云端主导、择机下放"，而是"**本地先干完，
云端只审查**"：Sonnet 用自己的 agent loop 独立修完 bug（随便用多少 token），
Fable 只拿到 diff + 报告，做验证、接受或救场。云端成本下限 = 纯审查成本。

## 三臂对比（云端成本，官方判分）

| 实例 | baseline | hybrid | local-first |
|---|---|---|---|
| flask-4992 | $0.182 ✅ | $0.108 ✅ | $0.072 ❌ |
| pylint-7993 | $0.164 ✅ | $0.119 ✅ | $0.132 ✅ |
| pytest-11143 | $0.100 ✅ | $0.155 ✅ | $0.094 ✅ |
| **合计** | **$0.447** (3/3) | **$0.381** (3/3) | **$0.297** (2/3) |
| vs baseline | — | **−15%** | **−34%** |

## 发现

1. **local-first 把云端成本又压低了一档**（−34% vs baseline，−22% vs hybrid），
   方向正确：本地免费时，能让本地做的都让本地做，云端只为"判断"付费。

2. **但暴露了质量悬崖**：flask 实例 NOT_RESOLVED。worker 给 `from_file()` 加的
   参数叫 `mode="r"`（issue 标题确实写的是 "file mode parameter"），功能上完全
   解决了问题、18 个配置测试全过；但官方隐藏测试期望维护者实际选择的 API
   `text=False`。云端审查者判定"accepted"——它验证了功能正确性，却无法预知
   隐藏测试的 API 偏好。（hybrid 臂中 Fable 自己写修复时恰好选了 `text=`。）

3. **审查成本不总是便宜**：pylint 的 local-first 云端花费（$0.132）反而高于
   hybrid（$0.119）——worker 跑了 20 轮产生大 diff，审查者读 diff + 验证的开销
   超过了 hybrid 中"直接自己修"的开销。审查成本 ∝ diff 大小与验证复杂度。

## 结论修正（本地免费口径）

- 省钱排序：**local-first (−34%) > hybrid (−15%) > baseline**，
  但 local-first 的解题率掉到 2/3。
- 真正的产品形态应是**置信度路由**：本地先试 → 云端审查；审查者不仅验证
  "功能对不对"，还要验证"是否符合任务的精确规格/API 约定"，对规格敏感或
  本地反复失败的任务升级为云端主导（hybrid/baseline 模式）。
- 这三臂数据点合在一起，正好给出了路由策略的损益边界：审查通过→省 60%+；
  审查漏判→白付审查费还要返工。路由器的准确率决定整套方案的期望收益。

---

# 扩样实验：11 实例 × 3 臂 = 33 数据点（最终统计）

3 实例的结论需要更大样本检验。从 32 个候选中自动验证出 **11 个可靠实例**
（验证项：venv 安装成功、修复前 F2P 必失败、官方金标补丁能使 F2P 通过、
P2P 基线 ≥5/10），覆盖 flask×3、pylint×4、pytest×4。

## 终表（云端成本，本地免费口径）

| 实例 | baseline | hybrid | local-first |
|---|---|---|---|
| flask-4045 | ❌ $0.136 | ❌ $0.113 | ✅ $0.323 |
| flask-4992 | ✅ $0.182 | ✅ $0.108 | ❌ $0.071 |
| flask-5063 | ✅ $0.256 | ✅ $0.282 | ❌ $0.196 |
| pylint-6506 | ✅ $0.477 | ✅ $0.288 | ✅ $0.343 |
| pylint-7114 | ✅ $0.924 | ✅ **$2.284** | ❌ $0.619 |
| pylint-7228 | ✅ $0.208 | ✅ $0.239 | ✅ $0.312 |
| pylint-7993 | ✅ $0.164 | ✅ $0.118 | ✅ $0.132 |
| pytest-11143 | ✅ $0.100 | ✅ $0.155 | ✅ $0.094 |
| pytest-11148 | ✅ $0.226 | ✅ $0.219 | ✅ $0.381 |
| pytest-8906 | ✅ $0.333 | ✅ $0.280 | ✅ $0.344 |
| pytest-9359 | ✅ $0.195 | ✅ $0.168 | ✅ $0.309 |
| **解题率** | **10/11 (91%)** | **10/11 (91%)** | 8/11 (73%) |
| **云端合计** | $3.202 | $4.256 (+33%) | $3.124 (−2.5%) |
| **中位数/题** | $0.208 | $0.219 | $0.312 |

## 扩样后的结论修正（重要）

1. **小样本结论没有复现。** 3 实例时 hybrid −15%、local-first −34%；扩到 11 实例后
   hybrid +33%（被一个离群值拖垮）、local-first 仅 −2.5% 且解题率掉到 73%。
   **在 SWE-bench 形态的 bug 修复任务上，纯云端 baseline 就是当前的成本-质量最优点。**

2. **重尾风险是 hybrid 的结构性弱点。** pylint-7114（命名空间包解析，最难的一题）上
   hybrid 花了 $2.28 = baseline 的 2.5 倍：编排者反复委派-验证-纠正，陷入昂贵的
   协调循环。剔除该离群值后 hybrid 为 −13%——即 hybrid 的"典型"行为略省，
   但难题上的协调失控会一次性吞掉整批节省。逐题看 hybrid 7/11 比 baseline 便宜。

3. **local-first 的失败模式集中且有规律**：3 个失败里 2 个是"功能对但不合隐藏
   规格"（flask-4992 的 mode= vs text=、flask-5063），1 个是难题修不动（pylint-7114）。
   而且**中位成本反而最高**（$0.312）——审查+救场在难题上比自己修更贵。

4. **意外发现：模型多样性有价值。** flask-4045 两个 Fable 臂都失败，
   唯独 local-first 的 Sonnet worker 解出来了。不同模型犯不同的错，
   这是做"多臂路由+交叉验证"的直接证据。

5. **任务形态结论被强化**：代码生成型（calclang，产出密集）实测省 26%；
   bug 修复型（诊断密集）省 ~0%。AI station 的省钱叙事必须锚定在
   产出密集型工作负载（批量生成、测试、重构、文档）。

## 方法学备注

- 每实例-臂仅 1 次运行；agent 成本方差 ±50%，单题差异大多不显著，
  合计/中位数比单题可靠。预算允许时应做 3 重复取均值。
- local worker 由 Sonnet 4.6 扮演；真实端侧 30B 级模型的能力差距会进一步
  压低 local-first/hybrid 的解题率，结论偏乐观侧。

---

# escalation 臂补全（11/11，Fable 云端）

之前 3 个实例因 429 限流缺失，补跑后完整数据：

| 架构 | 解题率 | 云端合计 | vs baseline |
|---|---|---|---|
| baseline（纯云端） | 10/11 | $3.20 | — |
| **escalate**（本地先解，失败升级） | **11/11** | $5.49 | **+71%** ❌ |

**全部 11 题都升级了**（worker 从未可信地报 solved——它看不到隐藏判分测试，
且常在 20 轮上限前还在「锦上添花」没来得及输出 verdict）。escalation 退化成
「本地白跑一遍 + 云端每题从头接手」，故 +71%。

有意思的副作用：escalate 解题率 11/11 **高于** baseline 10/11——worker 放弃后
云端 fresh 接手，比 baseline 一次过更稳，恰好救回了 baseline 漏掉的那题。
但代价是把成本翻了 1.7 倍。

**与 HumanEval+ 的决定性对照**（见 `../humaneval/RESULTS_HUMANEVAL.md`）：
同一套 escalation 代码，SWE-bench +71%（全升级）、HumanEval+ −88%（94% 不升级）。
唯一区别是**本地能否自证正确**——这是省钱的唯一决定变量。

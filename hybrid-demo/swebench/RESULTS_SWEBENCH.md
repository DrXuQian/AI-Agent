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

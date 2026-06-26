#!/usr/bin/env python3
"""
AI Station 盈利测算器 —— 三档真实售价（人民币）+ 各档自己的实测省钱率。

关键：省钱率随档位变化（更强的本地模型 → 更好的上下文包 → 云端做得更少 → 省得更多）。
context-engine 在 SWE-bench（难任务）实测：
  单卡 Haiku≈Qwen-int4 : 见 ce_savings['1']（实测/待回填）
  双卡 Sonnet≈M3       : -23%
  四卡 Opus4.6≈GLM5.2  : -30%
可验证负载（escalate/TDD）省钱率更高（HumanEval+ 实测 -88%），且同样随档位上升。

用法:
  python3 profitability.py                      # 三档总表（各档用自己的省钱率）
  python3 profitability.py --rmb 40000 --monthly 1000 --savings 0.25
"""
import argparse

FX = 7.2  # CNY per USD

# 档位: 名称, 售价¥, int4模型, int4估计Verified, context-engine实测省钱率(难任务)
# 单卡省钱率待 Haiku-worker 实测回填；暂用保守估计 0.18（弱于双卡的 0.23）
TIERS = [
    ("单卡", 20000, "Qwen3.5-122B-A10B-int4", 68, 0.18),
    ("双卡", 40000, "MiniMax-M3-int4",        76, 0.23),
    ("四卡", 80000, "GLM-5.2-int4",           77, 0.30),
]


def payback_years(rmb, monthly_usd, savings, price_mult=1.0):
    hw_usd = rmb / FX
    annual = monthly_usd * 12 * savings * price_mult
    return (hw_usd / annual) if annual > 0 else float("inf")


def tag(y):
    return "✅" if y < 2.5 else ("⚠️" if y < 4 else "❌")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rmb", type=float, help="机器售价 人民币")
    ap.add_argument("--monthly", type=float, help="云端月消耗 USD")
    ap.add_argument("--savings", type=float, help="省钱率 0-1（覆盖档位默认）")
    ap.add_argument("--price-mult", type=float, default=1.0, help="云端涨价倍数")
    a = ap.parse_args()

    if a.rmb and a.monthly and a.savings:
        y = payback_years(a.rmb, a.monthly, a.savings, a.price_mult)
        print(f"售价 ¥{a.rmb:.0f} (≈${a.rmb/FX:.0f}) | 月消耗 ${a.monthly:.0f} | "
              f"省{a.savings*100:.0f}% | 涨价{a.price_mult}x")
        print(f"  → 回本 {y:.1f} 年  {tag(y)}")
        return

    print("=== 三档：售价 / int4 模型 / context-engine 难任务实测省钱率 ===")
    print(f"{'档位':5} {'¥':>7} {'≈$':>6}  {'int4模型':28} {'~Verified':>9} {'省钱率':>7}")
    for n, rmb, m, v, s in TIERS:
        note = "(估)" if n == "单卡" else "(实测)"
        print(f"{n:5} ¥{rmb:>5} ${rmb/FX:>5.0f}  {m:28} ~{v}%   −{int(s*100)}%{note}")

    print("\n=== 各档「难任务」回本：用本档实测省钱率（行=月消耗）===")
    print(f"{'月消耗':>8} | " + "  ".join(f"{n}(−{int(s*100)}%)".rjust(12) for n,_,_,_,s in TIERS))
    for mo in (150, 300, 600, 1000, 2000, 3000):
        cells = []
        for n, rmb, m, v, s in TIERS:
            y = payback_years(rmb, mo, s)
            cells.append(f"{y:.1f}y{tag(y)}".rjust(12))
        print(f"${mo:>5}/mo | " + "  ".join(cells))

    print("\n=== 各档 2年回本所需「云端月消耗」：难任务(本档率) / 可验证(假设省60%) ===")
    for n, rmb, m, v, s in TIERS:
        hard = (rmb/FX)/2/(12*s)
        veri = (rmb/FX)/2/(12*0.60)
        print(f"  {n} ¥{rmb}: 难任务 ≥${hard:.0f}/mo (−{int(s*100)}%) | 可验证 ≥${veri:.0f}/mo (−60%)")

    print(f"\n注: 汇率 {FX}; 本地免费; 省钱率随档位上升(强模型→更好上下文包→更省)。")
    print("    单卡 −18% 为保守估计(待 Haiku-worker 实测回填); 双卡 −23%、四卡 −30% 为实测。")
    print("    可验证负载(TDD/测试生成)省钱率更高(HumanEval+ 实测 −88%)。")


if __name__ == "__main__":
    main()

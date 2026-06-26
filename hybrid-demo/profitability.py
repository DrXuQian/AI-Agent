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
# 单卡实测 -0.12（即 +12%，反而更贵！弱本地→上下文包误导云端）；双卡/四卡为实测正值。
TIERS = [
    ("单卡", 20000, "Qwen3.5-122B-A10B-int4", 68, -0.12),
    ("双卡", 40000, "MiniMax-M3-int4",        76,  0.23),
    ("四卡", 80000, "GLM-5.2-int4",           77,  0.30),
]


def payback_years(rmb, monthly_usd, savings, price_mult=1.0):
    hw_usd = rmb / FX
    annual = monthly_usd * 12 * savings * price_mult
    return (hw_usd / annual) if annual > 0 else float("inf")


def tag(y):
    if y == float("inf") or y < 0: return "✖亏"   # 省钱率≤0：不省反亏
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

    def rate_str(s):
        return f"+{int(-s*100)}%(更贵!)" if s < 0 else f"−{int(s*100)}%"

    print("=== 三档：售价 / int4 模型 / context-engine 难任务实测省钱率 ===")
    print(f"{'档位':5} {'¥':>7} {'≈$':>6}  {'int4模型':26} {'~Verified':>9} {'难任务省钱':>11}")
    for n, rmb, m, v, s in TIERS:
        print(f"{n:5} ¥{rmb:>5} ${rmb/FX:>5.0f}  {m:26} ~{v}%   {rate_str(s):>11}(实测)")

    print("\n=== 各档「难任务」回本：用本档实测省钱率（行=月消耗）===")
    print(f"{'月消耗':>8} | " + "  ".join(f"{n}".rjust(12) for n,*_ in TIERS))
    for mo in (300, 600, 1000, 2000, 3000):
        cells = []
        for n, rmb, m, v, s in TIERS:
            y = payback_years(rmb, mo, s)
            cells.append((f"{y:.1f}y{tag(y)}" if s > 0 else "✖亏损").rjust(12))
        print(f"${mo:>5}/mo | " + "  ".join(cells))

    print("\n=== 各档 2年回本所需「云端月消耗」：难任务(本档率) / 可验证(按省60%) ===")
    for n, rmb, m, v, s in TIERS:
        veri = (rmb/FX)/2/(12*0.60)
        hard = (f"≥${(rmb/FX)/2/(12*s):.0f}/mo" if s > 0 else "永不回本(省钱率≤0)")
        print(f"  {n} ¥{rmb}: 难任务 {hard} | 可验证 ≥${veri:.0f}/mo")

    print(f"\n注: 汇率 {FX}; 本地免费。难任务=SWE-bench bug 修复(context-engine)。")
    print("    单卡 Haiku≈Qwen-int4 实测 +12%(反而更贵)：弱本地的上下文包误导云端。")
    print("    双卡 −23%(Sonnet代理)、四卡 −30%(Opus4.6代理) 为实测；存在能力门槛。")
    print("    可验证负载(TDD/测试生成)用 escalate，省钱率高得多(HumanEval+ 实测 −88%)。")


if __name__ == "__main__":
    main()

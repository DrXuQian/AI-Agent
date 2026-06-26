#!/usr/bin/env python3
"""
AI Station 盈利测算器 —— 三档真实售价（人民币）+ 各档自己的实测省钱率。

关键：省钱率随「档位 × 负载类型」二维变化。
难任务（context-engine, SWE-bench bug 修复）实测：
  单卡 Haiku≈Qwen-int4 : +12%（反而更贵！弱本地误导云端）
  双卡 Sonnet≈M3       : −23%
  四卡 Opus4.6≈GLM5.2  : −30%
简单/可验证任务（escalate, HumanEval+）实测：
  单卡 Haiku≈Qwen-int4 : −63%（25/30 本地自解；28/30 解题，2 假阳性）
  双卡 Sonnet≈M3       : −88%（29/31 本地自解；31/31 解题，零假阳性）
  四卡 Opus4.6≈GLM5.2  : ~−90%（外推）

用法:
  python3 profitability.py                      # 全部表格
  python3 profitability.py --rmb 40000 --monthly 1000 --savings 0.25
"""
import argparse

FX = 7.2  # CNY per USD

# 档位: 名称, 售价¥, int4模型, int4估计Verified,
#        难任务省钱率(context-engine), 简单/可验证省钱率(escalate)
TIERS = [
    ("单卡", 20000, "Qwen3.5-122B-A10B-int4", 68, -0.12, 0.63),
    ("双卡", 40000, "MiniMax-M3-int4",        76,  0.23, 0.88),
    ("四卡", 80000, "GLM-5.2-int4",           77,  0.30, 0.90),
]

EASY_FRAC = 0.80  # 混合负载: 80% 简单 + 20% 难（按任务数加权）

MONTHS = (300, 600, 1000, 2000, 3000)


def blended(hard, simple):
    return EASY_FRAC * simple + (1 - EASY_FRAC) * hard


def payback_years(rmb, monthly_usd, savings, price_mult=1.0):
    hw_usd = rmb / FX
    annual = monthly_usd * 12 * savings * price_mult
    return (hw_usd / annual) if annual > 0 else float("inf")


def tag(y):
    if y == float("inf") or y < 0: return "✖亏"   # 省钱率≤0：不省反亏
    return "✅" if y < 2.5 else ("⚠️" if y < 4 else "❌")


def rate_str(s):
    return f"+{int(-s*100)}%(更贵!)" if s < 0 else f"−{int(s*100)}%"


def payback_table(title, rate_idx_or_fn):
    """rate_idx_or_fn: int (TIERS 字段下标) 或 fn(hard, simple)->savings"""
    print(f"\n=== {title}（行=云端月消耗 USD）===")
    print(f"{'月消耗':>8} | " + "  ".join(f"{n}{rate_label(t, rate_idx_or_fn)}".rjust(16)
                                          for t in TIERS for n in [t[0]]))
    for mo in MONTHS:
        cells = []
        for t in TIERS:
            s = rate_of(t, rate_idx_or_fn)
            y = payback_years(t[1], mo, s)
            cells.append((f"{y:.1f}y {tag(y)}" if s > 0 else "✖亏损").rjust(16))
        print(f"${mo:>5}/mo | " + "  ".join(cells))


def rate_of(t, idx_or_fn):
    return idx_or_fn(t[4], t[5]) if callable(idx_or_fn) else t[idx_or_fn]


def rate_label(t, idx_or_fn):
    return f"({rate_str(rate_of(t, idx_or_fn))})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rmb", type=float)
    ap.add_argument("--monthly", type=float)
    ap.add_argument("--savings", type=float)
    ap.add_argument("--price-mult", type=float, default=1.0)
    a = ap.parse_args()

    if a.rmb and a.monthly and a.savings:
        y = payback_years(a.rmb, a.monthly, a.savings, a.price_mult)
        print(f"售价 ¥{a.rmb:.0f} (≈${a.rmb/FX:.0f}) | 月消耗 ${a.monthly:.0f} | "
              f"省{a.savings*100:.0f}% | 涨价{a.price_mult}x")
        print(f"  → 回本 {y:.1f} 年  {tag(y)}")
        return

    print("=== 三档：售价 / int4 模型 / 难任务 & 简单任务实测省钱率 ===")
    print(f"{'档位':5} {'¥':>7} {'≈$':>6}  {'int4模型':26} {'~Ver':>5} "
          f"{'难任务':>9} {'简单/可验证':>11}")
    for n, rmb, m, v, hard, simple in TIERS:
        print(f"{n:5} ¥{rmb:>5} ${rmb/FX:>5.0f}  {m:26} ~{v}% "
              f"{rate_str(hard):>9} {rate_str(simple):>11}")

    payback_table("难任务回本（context-engine 本档率）", 4)
    payback_table("简单/可验证任务回本（escalate 本档率）", 5)
    payback_table(f"混合负载回本（{round(EASY_FRAC*100)}% 简单 + "
                  f"{round((1-EASY_FRAC)*100)}% 难，按任务数加权）", blended)

    print("\n=== 各档 2 年回本所需「云端月消耗」===")
    for n, rmb, m, v, hard, simple in TIERS:
        bl = blended(hard, simple)
        def need(s): return f"≥${(rmb/FX)/2/(12*s):.0f}/mo" if s > 0 else "永不回本"
        print(f"  {n} ¥{rmb}: 难任务 {need(hard)} | 简单 {need(simple)} | "
              f"混合 {need(bl)}")

    print(f"\n注: 汇率 {FX}; 本地免费。✅<2.5y / ⚠️2.5–4y / ❌>4y。")
    print("    难任务=SWE-bench bug 修复(context-engine); 简单=HumanEval+(escalate)。")
    print("    简单任务上连单卡都省钱(−63%实测)：弱本地也能跑测试自证、整题自解。")
    print("    混合按任务数加权(80/20); 难任务烧 token/题更多, 实际混合会略偏难任务侧。")


if __name__ == "__main__":
    main()

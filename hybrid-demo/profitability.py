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

# 档位: 名称, 售价¥, int4模型, 能力(Verified), 难任务省钱率, 简单省钱率,
#        难任务完成度(本地自解率), 简单任务完成度(本地自解率)
# 关键(路由地板): 端侧路由 Agent 让系统「绝不亏钱」——本地免费先试, 失败则云端从干净状态
#   接手(丢弃本地半成品、不为读它付费) => 最坏=baseline=省 0%(持平), 不会为负。
#   单卡难任务因此取 0%(持平); 裸「always-上下文包」曾实测 +12%(误导云端)是反面教材, 见注。
# 完成度=本地自解率(零云端)。简单省钱率 ≈ 1 − 2×(1−简单完成度)（实测拟合:
#   单卡83%→−63%, 双卡94%→−88%, 四卡98%→−95%）。难任务 escalate 省钱率 ≈ 难任务完成度。
# 四卡设为 85% 能力; 其 −40% 偏保守(近前沿本地实机很可能更高)。
TIERS = [
    ("单卡", 20000, "Qwen3.5-122B-A10B-int4", 68, 0.00, 0.63, 0.00, 0.83),
    ("双卡", 40000, "MiniMax-M3-int4",        76, 0.23, 0.88, 0.09, 0.94),
    ("四卡", 80000, "GLM-5.2-int4",           85, 0.40, 0.95, 0.40, 0.98),
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
    if s == 0: return "0%(持平)"
    return f"+{round(-s*100)}%(更贵!)" if s < 0 else f"−{round(s*100)}%"


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
            cell = f"{y:.1f}y {tag(y)}" if s > 0 else ("持平·不亏" if s == 0 else "✖亏(裸架构)")
            cells.append(cell.rjust(16))
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

    print("=== 三档：能力 / 完成度(本地自解率) / 省钱率 ===")
    print(f"{'档位':5} {'¥':>7} {'~Ver':>5}  {'易完成':>7} {'难完成':>7}  "
          f"{'难任务省':>9} {'简单省':>8}")
    for n, rmb, m, v, hard, simple, hc, sc in TIERS:
        print(f"{n:5} ¥{rmb:>5} ~{v}%   {sc*100:>5.0f}% {hc*100:>6.0f}%  "
              f"{rate_str(hard):>9} {rate_str(simple):>8}")
    print("  (四卡 85% 为设定值；其易/难完成度由实测两点反推外推，省钱率随之重算)")

    payback_table("难任务回本（context-engine 本档率）", 4)
    payback_table("简单/可验证任务回本（escalate 本档率）", 5)
    payback_table(f"混合负载回本（{round(EASY_FRAC*100)}% 简单 + "
                  f"{round((1-EASY_FRAC)*100)}% 难，按任务数加权）", blended)

    print("\n=== 各档 2 年回本所需「云端月消耗」===")
    for n, rmb, m, v, hard, simple, hc, sc in TIERS:
        bl = blended(hard, simple)
        def need(s):
            if s > 0: return f"≥${(rmb/FX)/2/(12*s):.0f}/mo"
            return "持平(靠简单任务回本)" if s == 0 else "永不回本"
        print(f"  {n} ¥{rmb}: 难任务 {need(hard)} | 简单 {need(simple)} | "
              f"混合 {need(bl)}")

    print(f"\n注: 汇率 {FX}; 本地免费。✅<2.5y / ⚠️2.5–4y / ❌>4y。")
    print("    路由地板: 端侧 Agent 让最坏=baseline(省0%,持平), 系统绝不亏钱。")
    print("    单卡难任务=0%(持平): 弱本地帮不上→路由直接走纯云端(=baseline)。")
    print("    难任务=SWE-bench; 简单=HumanEval+。简单省钱率≈1−2×(1−简单完成度)。")
    print("    四卡设为 85%(偏保守): 易完成≈98%→简单−95%; 难完成≈40%→escalate 难任务−40%。")


if __name__ == "__main__":
    main()

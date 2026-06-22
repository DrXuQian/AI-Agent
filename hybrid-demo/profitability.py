#!/usr/bin/env python3
"""
AI Station 盈利测算器。基于实测省钱率，给定客户场景输出回本期。

省钱率(实测): 可验证生成 escalate -88% | 批量生成 hybrid -26% | 难bug修复 context-engine -23%

用法:
  python3 profitability.py                      # 跑内置三类买家场景
  python3 profitability.py --monthly 1200 --savings 0.30 --hw 15000 --price-mult 1.0
"""
import argparse

# 实测省钱率（云端成本下降比例，正数=省）
MEASURED = {
    "verifiable_gen (escalate)": 0.88,
    "batch_gen (hybrid)": 0.26,
    "hard_bugfix (context-engine)": 0.23,
}


def payback(monthly_usd, savings_rate, hw_usd, price_mult=1.0):
    """price_mult: 云端 token 未来涨价倍数（机器价值随之放大）。"""
    annual_saving = monthly_usd * 12 * savings_rate * price_mult
    years = hw_usd / annual_saving if annual_saving > 0 else float("inf")
    return annual_saving, years


def verdict(years):
    if years < 1.5: return "✅ 强盈利 (<1.5年)"
    if years < 2.5: return "✅ 盈利 (1.5-2.5年)"
    if years < 4:   return "⚠️ 勉强 (2.5-4年)"
    return "❌ 不成立 (>4年)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--monthly", type=float, help="云端月消耗 USD")
    ap.add_argument("--savings", type=float, help="混合省钱率 0-1")
    ap.add_argument("--hw", type=float, help="硬件价格 USD")
    ap.add_argument("--price-mult", type=float, default=1.0, help="云端涨价倍数")
    a = ap.parse_args()

    print("=== 实测省钱率（参考）===")
    for k, v in MEASURED.items():
        print(f"  {k:34} -{v*100:.0f}%")

    if a.monthly and a.savings and a.hw:
        s, y = payback(a.monthly, a.savings, a.hw, a.price_mult)
        print(f"\n月消耗 ${a.monthly:.0f} | 省钱率 {a.savings*100:.0f}% | 硬件 ${a.hw:.0f}"
              f" | 涨价 {a.price_mult}x")
        print(f"  年节省 ${s:.0f}  →  回本 {y:.1f} 年  {verdict(y)}")
        return

    print("\n=== 内置场景（省钱率 30%，当前价格）===")
    scenarios = [
        ("个人重度用户", 150, 0.30, 4000),
        ("小团队8人共享", 1200, 0.30, 15000),
        ("重度agentic/CI团队", 3000, 0.30, 20000),
        ("CI团队+可验证负载", 3000, 0.50, 20000),
    ]
    print(f"{'场景':22} {'月消耗':>8} {'省率':>5} {'硬件':>8} {'年省':>8} {'回本':>7}  判定")
    for name, m, s, hw in scenarios:
        ann, yr = payback(m, s, hw)
        print(f"{name:22} ${m:>6.0f} {s*100:>4.0f}% ${hw:>6.0f} ${ann:>6.0f} {yr:>5.1f}年  {verdict(yr)}")

    print("\n=== 涨价敏感性（重度团队 $3000/月, 省30%, 硬件$20k）===")
    for mult in (1.0, 1.5, 2.0, 3.0):
        ann, yr = payback(3000, 0.30, 20000, mult)
        print(f"  云端涨价 {mult}x → 年省 ${ann:.0f}, 回本 {yr:.1f}年  {verdict(yr)}")


if __name__ == "__main__":
    main()

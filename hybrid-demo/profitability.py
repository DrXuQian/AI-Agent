#!/usr/bin/env python3
"""
AI Station 盈利测算器 —— 三档真实售价（人民币）+ int4 端侧模型。

实测省钱率（云端成本下降比例，仅计云端 Opus 4.8 token；本地免费）：
  难bug修复 context-engine -23% | 可验证生成 escalate -88%
  （单卡 int4 模型能力 ≈ 实验代理 Haiku 4.5，故单卡档省钱率被实测覆盖；
   双卡/四卡模型更强，省钱率只增不减）

用法:
  python3 profitability.py                      # 三档回本总表
  python3 profitability.py --rmb 24000 --monthly 600 --savings 0.30
"""
import argparse

FX = 7.2  # CNY per USD

# 档位: 名称, 售价¥, int4模型, int4估计Verified
TIERS = [
    ("单卡", 15000, "Qwen3.5-122B-A10B-int4", 68),
    ("双卡", 24000, "MiniMax-M3-int4", 76),
    ("四卡", 54000, "GLM-5.2-int4", 77),
]
RATES = [0.23, 0.30, 0.50, 0.88]


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
    ap.add_argument("--savings", type=float, help="混合省钱率 0-1")
    ap.add_argument("--price-mult", type=float, default=1.0, help="云端涨价倍数")
    a = ap.parse_args()

    if a.rmb and a.monthly and a.savings:
        y = payback_years(a.rmb, a.monthly, a.savings, a.price_mult)
        print(f"售价 ¥{a.rmb:.0f} (≈${a.rmb/FX:.0f}) | 月消耗 ${a.monthly:.0f} | "
              f"省{a.savings*100:.0f}% | 涨价{a.price_mult}x")
        print(f"  → 回本 {y:.1f} 年  {tag(y)}")
        return

    print("=== 三档：售价 与 int4 端侧模型 ===")
    print(f"{'档位':5} {'¥':>7} {'≈$':>6}  {'int4模型':32} {'~Verified':>9}")
    for n, rmb, m, v in TIERS:
        print(f"{n:5} ¥{rmb:>5} ${rmb/FX:>5.0f}  {m:32} ~{v}%")

    print("\n=== 2年回本所需「云端月消耗USD」（行=档位, 列=省钱率）===")
    print(f"{'档位':5} | " + "  ".join(f"省{int(r*100)}%".rjust(9) for r in RATES))
    for n, rmb, m, v in TIERS:
        need = (rmb / FX) / 2.0
        cells = [f"${need/(12*r):.0f}/mo".rjust(9) for r in RATES]
        print(f"{n:5} | " + "  ".join(cells))

    print("\n=== 回本年数（省钱率30%, 行=月消耗, 列=档位）===")
    print(f"{'月消耗':>8} | " + "  ".join(n.rjust(8) for n, *_ in TIERS))
    for mo in (150, 300, 600, 1000, 2000):
        cells = []
        for n, rmb, m, v in TIERS:
            y = payback_years(rmb, mo, 0.30)
            cells.append(f"{y:.1f}y{tag(y)}".rjust(8))
        print(f"${mo:>5}/mo | " + "  ".join(cells))

    print(f"\n注: 汇率 {FX} CNY/USD; 云端API按USD计; 本地算力免费;")
    print("    int4 Verified 为全精度掉~3-4分的估计, 待官方榜确认。")


if __name__ == "__main__":
    main()

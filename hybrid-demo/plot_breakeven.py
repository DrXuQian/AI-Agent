#!/usr/bin/env python3
"""Payback-years vs monthly cloud spend for the realistic BLENDED workload
(80% easy + 20% hard), per hardware tier, with 1-year and 2-year break-even
turning points marked."""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

FX = 7.2
TARGETS = [(2.0, "2-yr break-even", "gray"), (1.0, "1-yr break-even", "#444")]

# (label, price¥, blended-80/20 savings, color, label offset (x,y) pts)
TIERS = [
    ("Single-card  ¥20k", 20000, 0.48, "#1f77b4", (-46, -20)),
    ("Dual-card    ¥40k", 40000, 0.75, "#ff7f0e", (8, 9)),
    ("Quad-card    ¥80k", 80000, 0.78, "#2ca02c", (8, 9)),
]

monthly = np.linspace(100, 3000, 500)


def payback(rmb, m, s):
    return (rmb / FX) / (m * 12 * s)


def breakeven_month(rmb, s, years):
    return (rmb / FX) / (years * 12 * s)


fig, ax = plt.subplots(figsize=(11, 7))

for label, rmb, s, color, off in TIERS:
    ax.plot(monthly, payback(rmb, monthly, s), color=color, lw=2.4,
            label=f"{label}  (−{int(s*100)}%)")
    for years, _, _ in TARGETS:
        bx = breakeven_month(rmb, s, years)
        if bx <= 3000:
            ax.plot([bx], [years], "o", color=color, ms=9,
                    markeredgecolor="white", zorder=5)
            ax.annotate(f"${bx:.0f}/mo", (bx, years),
                        textcoords="offset points", xytext=off,
                        color=color, fontsize=10, fontweight="bold")

for years, txt, c in TARGETS:
    ax.axhline(years, ls="--", color=c, lw=1.3)
    ax.text(2960, years + 0.08, txt, ha="right", color=c, fontsize=9.5)

ax.axhspan(0, 1.0, color="green", alpha=0.10)
ax.axhspan(1.0, 2.0, color="green", alpha=0.04)
ax.set_xlabel("Monthly cloud spend (USD)", fontsize=11)
ax.set_ylabel("Payback period (years)  — lower is better", fontsize=11)
ax.set_xlim(100, 3000)
ax.set_ylim(0, 6)
ax.grid(alpha=0.25)
ax.legend(loc="upper right", fontsize=10, framealpha=0.95)
ax.set_title("AI Station break-even — blended load (80% easy + 20% hard)\n"
             "local compute free; only cloud token cost counts; "
             "markers = $/mo where payback crosses 1-yr / 2-yr",
             fontsize=12.5, fontweight="bold")
fig.tight_layout()
out = "/home/user/AI-Agent/hybrid-demo/breakeven.png"
fig.savefig(out, dpi=130, bbox_inches="tight")
print("wrote", out)

print("\nBlended-load break-even monthly spend:")
for label, rmb, s, *_ in TIERS:
    print(f"  {label}: 2-yr ${breakeven_month(rmb, s, 2):.0f}/mo | "
          f"1-yr ${breakeven_month(rmb, s, 1):.0f}/mo")

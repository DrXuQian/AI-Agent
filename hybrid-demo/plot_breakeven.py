#!/usr/bin/env python3
"""Payback-years vs monthly cloud spend, per hardware tier, with 2-year
break-even turning points marked. Two panels: hard-task workload (where weak
local backfires) vs realistic blended 80/20 workload."""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

FX = 7.2
TARGET_YEARS = 2.0  # the "✅" break-even line

# (label, price¥, hard savings, blended-80/20 savings)
TIERS = [
    ("Single-card  ¥20k", 20000, -0.12, 0.48, "#1f77b4"),
    ("Dual-card    ¥40k", 40000,  0.23, 0.75, "#ff7f0e"),
    ("Quad-card    ¥80k", 80000,  0.30, 0.78, "#2ca02c"),
]

monthly = np.linspace(100, 3000, 400)


def payback(rmb, m, s):
    hw = rmb / FX
    return np.where(s > 0, hw / (m * 12 * s), np.nan)


def breakeven_month(rmb, s):
    return (rmb / FX) / (TARGET_YEARS * 12 * s) if s > 0 else None


fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharey=True)

for ax, (title, idx) in zip(axes, [("Hard tasks (SWE-bench bug-fix)", 2),
                                    ("Blended load (80% easy + 20% hard)", 3)]):
    for label, rmb, hard, blend, color in TIERS:
        s = hard if idx == 2 else blend
        if s <= 0:
            ax.plot([], [], color=color, lw=2.2,
                    label=f"{label}  (+{int(-s*100)}% → never)")
            continue
        y = payback(rmb, monthly, s)
        ax.plot(monthly, y, color=color, lw=2.2,
                label=f"{label}  (−{int(s*100)}%)")
        bx = breakeven_month(rmb, s)
        if bx and bx <= 3000:
            ax.plot([bx], [TARGET_YEARS], "o", color=color, ms=9,
                    markeredgecolor="white", zorder=5)
            ax.annotate(f"${bx:.0f}/mo", (bx, TARGET_YEARS),
                        textcoords="offset points", xytext=(6, 10),
                        color=color, fontsize=10, fontweight="bold")

    ax.axhline(TARGET_YEARS, ls="--", color="gray", lw=1.2)
    ax.text(2950, TARGET_YEARS + 0.12, "2-yr break-even", ha="right",
            color="gray", fontsize=9)
    ax.axhspan(0, TARGET_YEARS, color="green", alpha=0.05)
    ax.set_title(title, fontsize=12, fontweight="bold")
    ax.set_xlabel("Monthly cloud spend (USD)")
    ax.set_xlim(100, 3000)
    ax.set_ylim(0, 8)
    ax.grid(alpha=0.25)
    ax.legend(loc="upper right", fontsize=9, framealpha=0.95)

axes[0].set_ylabel("Payback period (years)  — lower is better")
fig.suptitle("AI Station break-even: payback vs monthly cloud spend by tier\n"
             "(local compute free; only cloud token cost counts; markers = $/mo "
             "where payback crosses 2 years)",
             fontsize=13, fontweight="bold")
fig.tight_layout(rect=[0, 0, 1, 0.94])
out = "/home/user/AI-Agent/hybrid-demo/breakeven.png"
fig.savefig(out, dpi=130, bbox_inches="tight")
print("wrote", out)

# print the turning points for the report
print("\n2-year break-even monthly spend:")
for label, rmb, hard, blend, _ in TIERS:
    h = breakeven_month(rmb, hard)
    b = breakeven_month(rmb, blend)
    print(f"  {label}: hard={'never' if not h else f'${h:.0f}/mo'} | "
          f"blended=${b:.0f}/mo")

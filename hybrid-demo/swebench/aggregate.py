#!/usr/bin/env python3
"""Aggregate all per-run results into the final 3-arm comparison table."""
import glob
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ARMS = ["baseline", "hybrid", "localfirst"]


def cloud_cost(meter):
    if "cloud_cost" in meter:
        return meter["cloud_cost"]
    return meter.get("claude-fable-5", {}).get("cost", 0.0)


def main():
    iids = json.load(open(f"{HERE}/validated_ids.json"))
    rows = []
    for iid in iids:
        row = {"iid": iid}
        for arm in ARMS:
            rj = f"{HERE}/result_{iid}_{arm}.json"
            ev = f"{HERE}/eval_{iid}_{arm}.txt"
            if not (os.path.exists(rj) and os.path.exists(ev)):
                row[arm] = None
                continue
            meter = json.load(open(rj))["meter"]
            txt = open(ev).read()
            resolved = bool(re.search(r"^RESOLVED", txt, re.M))
            deleg = meter.get("delegations", 0)
            row[arm] = {"cost": cloud_cost(meter), "resolved": resolved,
                        "deleg": deleg}
        rows.append(row)

    short = lambda i: i.replace("pallets__", "").replace("pylint-dev__", "").replace("pytest-dev__", "")
    print(f"{'instance':<22}" + "".join(f"{a:>22}" for a in ARMS))
    for row in rows:
        line = f"{short(row['iid']):<22}"
        for arm in ARMS:
            c = row[arm]
            line += f"{'—':>22}" if c is None else \
                f"{'✅' if c['resolved'] else '❌'} ${c['cost']:.3f} d{c['deleg']:>17}"[:22].rjust(22)
        print(line)

    print("\n=== AGGREGATE (cloud cost only; local worker assumed free) ===")
    for arm in ARMS:
        done = [r[arm] for r in rows if r[arm]]
        if not done:
            continue
        n = len(done)
        solved = sum(1 for c in done if c["resolved"])
        total = sum(c["cost"] for c in done)
        print(f"{arm:<11} n={n:>2}  resolved={solved}/{n} ({solved/n*100:.0f}%)  "
              f"cloud total=${total:.3f}  mean=${total/n:.4f}")
    base = [r for r in rows if all(r[a] for a in ARMS)]
    if base:
        bt = sum(r["baseline"]["cost"] for r in base)
        for arm in ("hybrid", "localfirst"):
            at = sum(r[arm]["cost"] for r in base)
            print(f"{arm} vs baseline (paired n={len(base)}): "
                  f"{(at-bt)/bt*100:+.1f}% cloud cost")


if __name__ == "__main__":
    main()

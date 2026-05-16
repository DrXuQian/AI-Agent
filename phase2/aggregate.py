#!/usr/bin/env python3
"""Phase 2 aggregator.

Reads all runs/*.json, computes mean/std/p95 per (task_id, cache_mode),
emits:
  - phase2/results/summary.csv      flat per-(task, cache) rows
  - phase2/results/summary.json     same data, structured
  - phase2/results/report.md        markdown report with tables
"""

import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

PHASE2_DIR = Path(__file__).resolve().parent
RUNS_DIR = PHASE2_DIR / "runs"
OUT_DIR = PHASE2_DIR / "results"
OUT_DIR.mkdir(parents=True, exist_ok=True)


METRICS_NUMERIC = [
    "wall_sec",
    "metrics.prefill_p50_sec", "metrics.prefill_p95_sec",
    "metrics.decode_p50_sec",  "metrics.decode_p95_sec",
    "metrics.ttft_p50_sec",    "metrics.ttft_p95_sec",
    "metrics.tbt_p50_sec",     "metrics.tbt_p95_sec",
    "metrics.e2e_p50_sec",     "metrics.e2e_p95_sec",
    "metrics.prompt_tokens",   "metrics.generation_tokens",
    "metrics.request_count",
    "metrics.prefix_cache_hit_rate",
    "metrics.prompt_tokens_cached",
    "metrics.kv_cache_usage_pct_avg",
    "metrics.kv_cache_usage_pct_max",
    "metrics.prefill_tps",
    "metrics.decode_tps",
]


def get_path(obj: dict, dotted: str):
    cur = obj
    for k in dotted.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def aggregate_runs(runs: list[dict]) -> dict:
    """Compute mean/std for each numeric metric across runs."""
    agg = {"n_runs": len(runs)}
    n_ok = sum(1 for r in runs if r.get("exit_code") == 0 and not r.get("timed_out"))
    agg["n_ok"] = n_ok
    agg["success_rate"] = n_ok / len(runs) if runs else 0
    for key in METRICS_NUMERIC:
        values = [get_path(r, key) for r in runs]
        values = [v for v in values if isinstance(v, (int, float))]
        if not values:
            agg[f"{key}.mean"] = None
            agg[f"{key}.std"] = None
            continue
        agg[f"{key}.mean"] = round(statistics.mean(values), 4)
        agg[f"{key}.std"] = round(statistics.stdev(values), 4) if len(values) > 1 else 0.0
    return agg


def main():
    # Load all run files
    runs = []
    for p in sorted(RUNS_DIR.glob("*.json")):
        try:
            runs.append(json.loads(p.read_text()))
        except Exception as e:
            print(f"Skip {p}: {e}", file=sys.stderr)
    if not runs:
        print("No runs found. Run runner.py first.")
        sys.exit(1)

    # Group by (task_id, cache_mode)
    groups = defaultdict(list)
    for r in runs:
        key = (r["task_id"], r.get("cache_mode", "unknown"), r.get("agent", "unknown"))
        groups[key].append(r)

    # Aggregate
    rows = []
    for (task_id, cache_mode, agent), group_runs in sorted(groups.items()):
        agg = aggregate_runs(group_runs)
        agg["task_id"] = task_id
        agg["cache_mode"] = cache_mode
        agg["agent"] = agent
        agg["category"] = group_runs[0].get("category", "")
        rows.append(agg)

    # Write CSV
    csv_path = OUT_DIR / "summary.csv"
    if rows:
        fieldnames = ["task_id", "cache_mode", "agent", "category", "n_runs", "n_ok", "success_rate"] + \
                     [k for k in rows[0] if k not in ("task_id", "cache_mode", "agent", "category", "n_runs", "n_ok", "success_rate")]
        with open(csv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)
        print(f"Wrote {csv_path}")

    # Write JSON
    json_path = OUT_DIR / "summary.json"
    json_path.write_text(json.dumps(rows, indent=2, default=str))
    print(f"Wrote {json_path}")

    # Build markdown report
    report = []
    report.append("# Phase 2 Benchmark Report\n")
    report.append(f"Generated from `{len(runs)}` total runs across `{len(groups)}` (task, cache) groups.\n")

    # ===== Per-task summary table =====
    report.append("## Per-task summary\n")
    report.append("Time per task (wall clock, mean ± std across runs):\n")
    report.append("| Task | Agent | Cache | n | OK | Wall sec (mean) | Wall sec (std) | TTFT p50 | Prefill TPS | Cache hit |")
    report.append("|---|---|---|---|---|---|---|---|---|---|")
    for row in rows:
        report.append(
            f"| `{row['task_id']}` | {row['agent']} | {row['cache_mode']} | "
            f"{row['n_runs']} | {row['n_ok']} | "
            f"{row.get('wall_sec.mean', '-')} | {row.get('wall_sec.std', '-')} | "
            f"{row.get('metrics.ttft_p50_sec.mean', '-')} | "
            f"{row.get('metrics.prefill_tps.mean', '-')} | "
            f"{row.get('metrics.prefix_cache_hit_rate.mean', '-')} |"
        )
    report.append("")

    # ===== Cache on vs off comparison =====
    report.append("## Cache ON vs OFF\n")
    report.append("Same task, comparing cache modes (positive = cache helps):\n")
    report.append("| Task | Wall sec (ON) | Wall sec (OFF) | Δ wall | TTFT p50 (ON) | TTFT p50 (OFF) | Δ TTFT |")
    report.append("|---|---|---|---|---|---|---|")
    by_task = defaultdict(dict)
    for row in rows:
        by_task[row["task_id"]][row["cache_mode"]] = row
    for tid, modes in sorted(by_task.items()):
        on = modes.get("on", {})
        off = modes.get("off", {})
        if not on or not off:
            continue
        wall_on = on.get("wall_sec.mean")
        wall_off = off.get("wall_sec.mean")
        ttft_on = on.get("metrics.ttft_p50_sec.mean")
        ttft_off = off.get("metrics.ttft_p50_sec.mean")
        def diff(a, b):
            if a is None or b is None:
                return "-"
            return f"{(b - a):+.2f}" if isinstance(a, (int, float)) else "-"
        report.append(
            f"| `{tid}` | {wall_on} | {wall_off} | {diff(wall_on, wall_off)} | "
            f"{ttft_on} | {ttft_off} | {diff(ttft_on, ttft_off)} |"
        )
    report.append("")

    # ===== Agent profile comparison =====
    report.append("## Agent profile: OpenClaw vs Claude Code\n")
    by_agent = defaultdict(list)
    for row in rows:
        if row["cache_mode"] == "on":
            by_agent[row["agent"]].append(row)
    for agent, rs in by_agent.items():
        if not rs:
            continue
        wall = [r["wall_sec.mean"] for r in rs if r.get("wall_sec.mean")]
        tps_p = [r.get("metrics.prefill_tps.mean") for r in rs if r.get("metrics.prefill_tps.mean")]
        tps_d = [r.get("metrics.decode_tps.mean") for r in rs if r.get("metrics.decode_tps.mean")]
        cache = [r.get("metrics.prefix_cache_hit_rate.mean") for r in rs if r.get("metrics.prefix_cache_hit_rate.mean")]
        def stat(xs):
            if not xs:
                return "-"
            return f"{statistics.mean(xs):.2f}" + (f" ± {statistics.stdev(xs):.2f}" if len(xs) > 1 else "")
        report.append(f"### {agent} ({len(rs)} task types, cache=on)\n")
        report.append(f"- Mean wall time (s):     {stat(wall)}")
        report.append(f"- Mean prefill TPS:       {stat(tps_p)}")
        report.append(f"- Mean decode TPS:        {stat(tps_d)}")
        report.append(f"- Mean cache hit rate:    {stat(cache)}\n")

    md_path = OUT_DIR / "report.md"
    md_path.write_text("\n".join(report))
    print(f"Wrote {md_path}")
    print()
    print("=" * 60)
    print("Quick view:")
    print(f"  Total runs:   {len(runs)}")
    print(f"  Task groups:  {len(groups)}")
    print(f"  Success rate: {sum(1 for r in runs if r.get('exit_code') == 0 and not r.get('timed_out'))}/{len(runs)}")


if __name__ == "__main__":
    main()

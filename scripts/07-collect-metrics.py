#!/usr/bin/env python3
"""07-collect-metrics.py — Pull vLLM metrics from Prometheus for each task time window."""

import csv
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

BENCH_DIR = Path(__file__).resolve().parent.parent
RESULTS_DIR = BENCH_DIR / "results"
PROM_URL = os.environ.get("PROM_URL", "http://localhost:9091")

# ---- Prometheus query helper ----
def prom_query_range(query: str, start: float, end: float, step: int = 5) -> list:
    """Query Prometheus range API."""
    resp = requests.get(
        f"{PROM_URL}/api/v1/query_range",
        params={"query": query, "start": start, "end": end, "step": step},
    )
    resp.raise_for_status()
    data = resp.json()
    if data["status"] != "success":
        return []
    return data["data"]["result"]


def prom_query_instant(query: str, time_: float) -> list:
    """Query Prometheus instant API."""
    resp = requests.get(
        f"{PROM_URL}/api/v1/query",
        params={"query": query, "time": time_},
    )
    resp.raise_for_status()
    data = resp.json()
    if data["status"] != "success":
        return []
    return data["data"]["result"]


def extract_scalar(result: list) -> float | None:
    """Extract a single scalar from Prometheus result."""
    if not result:
        return None
    # For range queries, take the last value
    if "values" in result[0]:
        values = result[0]["values"]
        if values:
            v = float(values[-1][1])
            return v if v == v else None  # NaN check
    # For instant queries
    if "value" in result[0]:
        v = float(result[0]["value"][1])
        return v if v == v else None
    return None


# ---- Metrics to collect ----
METRICS = {
    # Latency histograms
    "prefill_p50_sec": 'histogram_quantile(0.5, rate(vllm:request_prefill_time_seconds_bucket{{model_name="qwen35"}}[{window}]))',
    "prefill_p95_sec": 'histogram_quantile(0.95, rate(vllm:request_prefill_time_seconds_bucket{{model_name="qwen35"}}[{window}]))',
    "decode_p50_sec": 'histogram_quantile(0.5, rate(vllm:request_decode_time_seconds_bucket{{model_name="qwen35"}}[{window}]))',
    "decode_p95_sec": 'histogram_quantile(0.95, rate(vllm:request_decode_time_seconds_bucket{{model_name="qwen35"}}[{window}]))',
    "ttft_p50_sec": 'histogram_quantile(0.5, rate(vllm:time_to_first_token_seconds_bucket{{model_name="qwen35"}}[{window}]))',
    "ttft_p95_sec": 'histogram_quantile(0.95, rate(vllm:time_to_first_token_seconds_bucket{{model_name="qwen35"}}[{window}]))',
    "e2e_p50_sec": 'histogram_quantile(0.5, rate(vllm:e2e_request_latency_seconds_bucket{{model_name="qwen35"}}[{window}]))',
    # Throughput
    "prompt_tokens_total": 'sum(increase(vllm:prompt_tokens_total{{model_name="qwen35"}}[{window}]))',
    "generation_tokens_total": 'sum(increase(vllm:generation_tokens_total{{model_name="qwen35"}}[{window}]))',
    "request_count": 'sum(increase(vllm:request_success_total{{model_name="qwen35"}}[{window}]))',
    # Cache
    "prefix_cache_hit_rate": 'increase(vllm:prefix_cache_hits_total{{model_name="qwen35"}}[{window}]) / clamp_min(increase(vllm:prefix_cache_queries_total{{model_name="qwen35"}}[{window}]), 1)',
    "prefix_cache_hits": 'increase(vllm:prefix_cache_hits_total{{model_name="qwen35"}}[{window}])',
    "prefix_cache_queries": 'increase(vllm:prefix_cache_queries_total{{model_name="qwen35"}}[{window}])',
    "prompt_tokens_cached": 'increase(vllm:prompt_tokens_cached_total{{model_name="qwen35"}}[{window}])',
    "gpu_cache_usage_pct": 'avg_over_time(vllm:kv_cache_usage_perc{{model_name="qwen35"}}[{window}])',
    # Throughput rates
    "tps_decode": 'rate(vllm:generation_tokens_total{{model_name="qwen35"}}[{window}])',
    "tps_prefill": 'rate(vllm:prompt_tokens_total{{model_name="qwen35"}}[{window}])',
}


def collect_for_task(task_name: str, start: float, end: float) -> dict:
    """Collect all metrics for a task's time window."""
    duration = int(end - start)
    window = f"{max(duration, 60)}s"  # minimum 60s window for rate()

    result = {
        "task": task_name,
        "start": datetime.fromtimestamp(start).isoformat(),
        "end": datetime.fromtimestamp(end).isoformat(),
        "duration_sec": duration,
        "metrics": {},
    }

    for name, query_tmpl in METRICS.items():
        query = query_tmpl.format(window=window)
        try:
            data = prom_query_instant(query, end)
            value = extract_scalar(data)
            result["metrics"][name] = value
        except Exception as e:
            result["metrics"][name] = f"ERROR: {e}"

    return result


def main():
    # Read time windows
    csv_path = RESULTS_DIR / "time_windows.csv"
    if not csv_path.exists():
        print(f"ERROR: {csv_path} not found. Run 06-run-tasks.sh first.")
        sys.exit(1)

    tasks = []
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            tasks.append(row)

    if not tasks:
        print("ERROR: No tasks found in time_windows.csv")
        sys.exit(1)

    # Collect metrics for each task
    all_results = []
    for task in tasks:
        name = task["task"]
        start = float(task["start_epoch"])
        end = float(task["end_epoch"])
        print(f"Collecting metrics for: {name} ({end - start:.0f}s window)")
        result = collect_for_task(name, start, end)
        all_results.append(result)

        # Print summary
        m = result["metrics"]
        print(f"  TTFT p50:         {m.get('ttft_p50_sec')}")
        print(f"  Prefill p50:      {m.get('prefill_p50_sec')}")
        print(f"  Decode p50:       {m.get('decode_p50_sec')}")
        print(f"  Prompt tokens:    {m.get('prompt_tokens_total')}")
        print(f"  Gen tokens:       {m.get('generation_tokens_total')}")
        print(f"  Request count:    {m.get('request_count')}")
        print(f"  Cache hit rate:   {m.get('prefix_cache_hit_rate')}")
        print(f"  KV usage %:       {m.get('gpu_cache_usage_pct')}")
        print()

    # Save full results
    out_path = RESULTS_DIR / "phase1_metrics.json"
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"Full results saved to {out_path}")

    # ---- Comparison table ----
    print("\n" + "=" * 70)
    print("COMPARISON: OpenClaw vs Claude Code")
    print("=" * 70)
    if len(all_results) >= 2:
        headers = ["Metric", all_results[0]["task"], all_results[1]["task"]]
        rows = []
        for key in METRICS:
            v0 = all_results[0]["metrics"].get(key)
            v1 = all_results[1]["metrics"].get(key)
            fmt = lambda v: f"{v:.4f}" if isinstance(v, (int, float)) else str(v)
            rows.append([key, fmt(v0), fmt(v1)])

        # Print table
        widths = [max(len(r[i]) for r in [headers] + rows) for i in range(3)]
        fmt_row = lambda r: " | ".join(r[i].ljust(widths[i]) for i in range(3))
        print(fmt_row(headers))
        print("-+-".join("-" * w for w in widths))
        for row in rows:
            print(fmt_row(row))


if __name__ == "__main__":
    main()

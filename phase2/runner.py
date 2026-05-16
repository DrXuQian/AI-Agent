#!/usr/bin/env python3
"""Phase 2 task runner.

Runs one task N times with proper setup/teardown isolation. Records timing,
output, agent metadata, and Prometheus metrics for each run.

Usage:
    runner.py --task <task_file> --runs 3 [--cache-mode on|off]
    runner.py --task-glob 'phase2/tasks/cc_*.yaml' --runs 3
"""

import argparse
import glob
import json
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
import yaml

BENCH_DIR = Path(__file__).resolve().parent.parent
PHASE2_DIR = BENCH_DIR / "phase2"
RUNS_DIR = PHASE2_DIR / "runs"
WORKSPACES_DIR = PHASE2_DIR / "workspaces"
RESULTS_DIR = BENCH_DIR / "results"

VLLM_PORT = int(os.environ.get("VLLM_PORT", "8000"))
PROM_URL = os.environ.get("PROM_URL", "http://localhost:9091")

RUNS_DIR.mkdir(parents=True, exist_ok=True)
WORKSPACES_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Variable substitution
# ---------------------------------------------------------------------------
def render(template: str, *, workspace: str, run_id: int) -> str:
    return (
        template.replace("{bench}", str(BENCH_DIR))
        .replace("{workspace}", workspace)
        .replace("{run_id}", str(run_id))
    )


# ---------------------------------------------------------------------------
# Prometheus metric collection
# ---------------------------------------------------------------------------
METRICS_QUERIES = {
    "prefill_p50_sec":          'histogram_quantile(0.5,  rate(vllm:request_prefill_time_seconds_bucket{{model_name="qwen35"}}[{w}]))',
    "prefill_p95_sec":          'histogram_quantile(0.95, rate(vllm:request_prefill_time_seconds_bucket{{model_name="qwen35"}}[{w}]))',
    "decode_p50_sec":           'histogram_quantile(0.5,  rate(vllm:request_decode_time_seconds_bucket{{model_name="qwen35"}}[{w}]))',
    "decode_p95_sec":           'histogram_quantile(0.95, rate(vllm:request_decode_time_seconds_bucket{{model_name="qwen35"}}[{w}]))',
    "ttft_p50_sec":             'histogram_quantile(0.5,  rate(vllm:time_to_first_token_seconds_bucket{{model_name="qwen35"}}[{w}]))',
    "ttft_p95_sec":             'histogram_quantile(0.95, rate(vllm:time_to_first_token_seconds_bucket{{model_name="qwen35"}}[{w}]))',
    "tbt_p50_sec":              'histogram_quantile(0.5,  rate(vllm:time_per_output_token_seconds_bucket{{model_name="qwen35"}}[{w}]))',
    "tbt_p95_sec":              'histogram_quantile(0.95, rate(vllm:time_per_output_token_seconds_bucket{{model_name="qwen35"}}[{w}]))',
    "e2e_p50_sec":              'histogram_quantile(0.5,  rate(vllm:e2e_request_latency_seconds_bucket{{model_name="qwen35"}}[{w}]))',
    "e2e_p95_sec":              'histogram_quantile(0.95, rate(vllm:e2e_request_latency_seconds_bucket{{model_name="qwen35"}}[{w}]))',
    "prompt_tokens":            'sum(increase(vllm:prompt_tokens_total{{model_name="qwen35"}}[{w}]))',
    "generation_tokens":        'sum(increase(vllm:generation_tokens_total{{model_name="qwen35"}}[{w}]))',
    "request_count":            'sum(increase(vllm:request_success_total{{model_name="qwen35"}}[{w}]))',
    "prefix_cache_hits":        'sum(increase(vllm:prefix_cache_hits_total{{model_name="qwen35"}}[{w}]))',
    "prefix_cache_queries":     'sum(increase(vllm:prefix_cache_queries_total{{model_name="qwen35"}}[{w}]))',
    "prompt_tokens_cached":     'sum(increase(vllm:prompt_tokens_cached_total{{model_name="qwen35"}}[{w}]))',
    "kv_cache_usage_pct_avg":   'avg_over_time(vllm:kv_cache_usage_perc{{model_name="qwen35"}}[{w}])',
    "kv_cache_usage_pct_max":   'max_over_time(vllm:kv_cache_usage_perc{{model_name="qwen35"}}[{w}])',
}


def query_prom(query: str, time_: float) -> float | None:
    try:
        r = requests.get(
            f"{PROM_URL}/api/v1/query",
            params={"query": query, "time": time_},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        if data["status"] != "success" or not data["data"]["result"]:
            return None
        v = float(data["data"]["result"][0]["value"][1])
        return v if v == v else None  # NaN check
    except Exception:
        return None


def collect_metrics(start: float, end: float) -> dict:
    window_sec = max(int(end - start), 30)  # min 30s for rate() stability
    w = f"{window_sec}s"
    metrics = {}
    # Add 10s buffer for last scrape to settle
    query_time = end + 10
    for name, q_tmpl in METRICS_QUERIES.items():
        metrics[name] = query_prom(q_tmpl.format(w=w), query_time)
    # Derive throughput
    pt = metrics.get("prompt_tokens") or 0
    gt = metrics.get("generation_tokens") or 0
    if window_sec > 0 and pt:
        metrics["prefill_tps"] = pt / window_sec
    if window_sec > 0 and gt:
        metrics["decode_tps"] = gt / window_sec
    # Cache hit rate
    hits = metrics.get("prefix_cache_hits") or 0
    queries = metrics.get("prefix_cache_queries") or 0
    if queries > 0:
        metrics["prefix_cache_hit_rate"] = hits / queries
    else:
        metrics["prefix_cache_hit_rate"] = None
    return metrics


# ---------------------------------------------------------------------------
# Agent invocation
# ---------------------------------------------------------------------------
def run_openclaw(prompt: str, workspace: str, timeout: int, log_path: Path) -> dict:
    """Run an OpenClaw agent task. Returns dict with stdout, exit_code, agent_meta."""
    session_id = f"bench-{int(time.time() * 1000)}"
    cmd = [
        "openclaw", "agent", "--local",
        "--model", "vllm-local/qwen35",
        "--session-id", session_id,
        "--json",
        "-m", prompt,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=workspace,
        )
        stdout = proc.stdout
        log_path.write_text(stdout + "\n---STDERR---\n" + proc.stderr)
        # Parse JSON output for agent metadata
        agent_meta = {}
        try:
            data = json.loads(stdout)
            agent_meta = data.get("meta", {}).get("agentMeta", {})
            agent_meta["toolSummary"] = data.get("meta", {}).get("toolSummary", {})
            agent_meta["durationMs"] = data.get("meta", {}).get("durationMs")
            agent_meta["stopReason"] = data.get("meta", {}).get("stopReason")
        except Exception:
            pass
        return {
            "exit_code": proc.returncode,
            "stdout_excerpt": stdout[:1000],
            "stderr_excerpt": proc.stderr[:500],
            "agent_meta": agent_meta,
            "timed_out": False,
        }
    except subprocess.TimeoutExpired:
        return {
            "exit_code": -1,
            "stdout_excerpt": "",
            "stderr_excerpt": f"TIMEOUT after {timeout}s",
            "agent_meta": {},
            "timed_out": True,
        }


def run_claude_code(
    prompt: str, workspace: str, timeout: int, allowed_tools: str, log_path: Path
) -> dict:
    """Run a Claude Code task. Returns dict with stdout, exit_code, agent_meta."""
    env = os.environ.copy()
    env.update({
        "ANTHROPIC_BASE_URL": f"http://localhost:{VLLM_PORT}",
        "ANTHROPIC_API_KEY": "dummy",
        "ANTHROPIC_AUTH_TOKEN": "dummy",
        "ANTHROPIC_DEFAULT_OPUS_MODEL": "qwen35",
        "ANTHROPIC_DEFAULT_SONNET_MODEL": "qwen35",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": "qwen35",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "DISABLE_PROMPT_CACHING": "1",
        # Limit Claude Code requested output so input has room within vLLM's
        # max_model_len. Default Claude Code requests 32K output which eats
        # half the 64K context budget — too tight for app-build tasks.
        "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "8192",
    })
    cmd = [
        "claude", "-p", prompt,
        "--allowedTools", allowed_tools,
        "--output-format", "stream-json",
        "--verbose",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=workspace,
            env=env,
            stdin=subprocess.DEVNULL,
        )
        stdout = proc.stdout
        log_path.write_text(stdout + "\n---STDERR---\n" + proc.stderr)
        # Parse stream-json lines for metadata
        agent_meta = {"tool_uses": 0, "messages": 0}
        try:
            for line in stdout.splitlines():
                try:
                    obj = json.loads(line)
                    if obj.get("type") == "assistant":
                        agent_meta["messages"] += 1
                        for c in obj.get("message", {}).get("content", []):
                            if c.get("type") == "tool_use":
                                agent_meta["tool_uses"] += 1
                    if obj.get("type") == "result":
                        agent_meta["result"] = {
                            "duration_ms": obj.get("duration_ms"),
                            "duration_api_ms": obj.get("duration_api_ms"),
                            "num_turns": obj.get("num_turns"),
                            "usage": obj.get("usage"),
                            "total_cost_usd": obj.get("total_cost_usd"),
                        }
                except Exception:
                    continue
        except Exception:
            pass
        return {
            "exit_code": proc.returncode,
            "stdout_excerpt": stdout[:1000],
            "stderr_excerpt": proc.stderr[:500],
            "agent_meta": agent_meta,
            "timed_out": False,
        }
    except subprocess.TimeoutExpired:
        return {
            "exit_code": -1,
            "stdout_excerpt": "",
            "stderr_excerpt": f"TIMEOUT after {timeout}s",
            "agent_meta": {},
            "timed_out": True,
        }


# ---------------------------------------------------------------------------
# Single run executor
# ---------------------------------------------------------------------------
def execute_setup(commands: list[str], workspace: str, run_id: int) -> int:
    for cmd in commands or []:
        rendered = render(cmd, workspace=workspace, run_id=run_id)
        result = subprocess.run(rendered, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  ! setup failed: {rendered}")
            print(f"    stderr: {result.stderr[:300]}")
            return result.returncode
    return 0


def run_one(task: dict, run_id: int, cache_mode: str, resume: bool = False) -> dict:
    workspace = str(WORKSPACES_DIR / f"{task['id']}-r{run_id}")
    log_path = RUNS_DIR / f"{task['id']}__cache{cache_mode}__r{run_id}.log"
    result_path = RUNS_DIR / f"{task['id']}__cache{cache_mode}__r{run_id}.json"

    # Resume: skip if a successful prior run is already on disk
    if resume and result_path.exists():
        try:
            prior = json.loads(result_path.read_text())
            if prior.get("exit_code") == 0 and not prior.get("timed_out"):
                print(f"  [skip] already passed: {result_path.name}")
                return prior
        except Exception:
            pass

    # Setup
    print(f"  [setup]")
    setup_rc = execute_setup(task.get("setup", []), workspace, run_id)
    if setup_rc != 0:
        return {"status": "setup_failed", "task_id": task["id"], "run_id": run_id}

    # Render prompt
    prompt = render(task["prompt"], workspace=workspace, run_id=run_id)
    timeout = int(task.get("timeout", 600))

    # Execute agent
    print(f"  [run] agent={task['agent']} timeout={timeout}s")
    start = time.time()
    if task["agent"] == "openclaw":
        outcome = run_openclaw(prompt, workspace, timeout, log_path)
    elif task["agent"] == "claude_code":
        allowed = task.get("allowed_tools", "Read,Edit,Write,Bash,Glob,Grep")
        outcome = run_claude_code(prompt, workspace, timeout, allowed, log_path)
    else:
        raise ValueError(f"unknown agent: {task['agent']}")
    end = time.time()
    wall_sec = end - start
    print(f"  [done] wall={wall_sec:.1f}s exit={outcome['exit_code']} timed_out={outcome['timed_out']}")

    # Collect metrics
    # Wait a bit for last Prometheus scrape
    time.sleep(7)
    print(f"  [metrics] collecting...")
    metrics = collect_metrics(start, end)

    # Teardown (optional, skip if you want to inspect)
    if os.environ.get("KEEP_WORKSPACES") != "1":
        execute_setup(task.get("teardown", []), workspace, run_id)

    # Save result
    result = {
        "task_id": task["id"],
        "agent": task["agent"],
        "category": task.get("category", ""),
        "run_id": run_id,
        "cache_mode": cache_mode,
        "start_epoch": start,
        "end_epoch": end,
        "wall_sec": round(wall_sec, 2),
        "exit_code": outcome["exit_code"],
        "timed_out": outcome["timed_out"],
        "agent_meta": outcome["agent_meta"],
        "metrics": metrics,
        "stdout_excerpt": outcome["stdout_excerpt"],
        "stderr_excerpt": outcome["stderr_excerpt"],
        "log_path": str(log_path),
        "timestamp": datetime.now().isoformat(),
    }
    result_path.write_text(json.dumps(result, indent=2, default=str))
    print(f"  [saved] {result_path.name}")
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def load_task(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", help="Single task yaml file")
    ap.add_argument("--task-glob", help="Glob pattern for task files")
    ap.add_argument("--runs", type=int, default=3, help="Repeats per task")
    ap.add_argument("--cache-mode", default="on", choices=["on", "off"], help="Just a label; vLLM flag set externally")
    ap.add_argument("--start-run", type=int, default=1, help="Starting run id (for resume)")
    ap.add_argument("--resume", action="store_true", help="Skip runs whose JSON already exists with exit_code=0")
    args = ap.parse_args()

    # Resolve task files
    task_files = []
    if args.task:
        task_files = [Path(args.task)]
    elif args.task_glob:
        task_files = sorted(Path(p) for p in glob.glob(args.task_glob))
    else:
        task_files = sorted((PHASE2_DIR / "tasks").glob("*.yaml"))
    if not task_files:
        print("No task files found")
        sys.exit(1)

    print(f"Loaded {len(task_files)} tasks, running {args.runs}x in cache={args.cache_mode} mode")
    print(f"Tasks: {[t.stem for t in task_files]}")
    print()

    summary = []
    for tf in task_files:
        task = load_task(tf)
        print(f"=== {task['id']} ===")
        for run_id in range(args.start_run, args.start_run + args.runs):
            print(f"-- run {run_id}/{args.runs}")
            try:
                result = run_one(task, run_id, args.cache_mode, resume=args.resume)
                summary.append(result)
            except Exception as e:
                print(f"  ! exception: {e}")
                summary.append({"task_id": task["id"], "run_id": run_id, "error": str(e)})
        print()

    print(f"Done. {len(summary)} runs total. Output in {RUNS_DIR}/")


if __name__ == "__main__":
    main()

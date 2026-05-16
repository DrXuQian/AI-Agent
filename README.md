# Agent Bench: vLLM × OpenClaw × Claude Code

End-to-end benchmark for measuring agent workloads (Claude Code for coding, OpenClaw
for personal-assistant tasks) running against a local vLLM-served Qwen3.5-35B-A3B model,
with Prometheus + Grafana for metric collection.

## Hardware tested

- 1× NVIDIA H800 PCIe (80 GB) — TP=1
- Linux, Node 24+, Python 3.12+

## Quickstart

```bash
# Phase 1: smoke test (1 OpenClaw task + 1 Claude Code task, validates pipeline)
bash run-phase1.sh

# Phase 2: full benchmark (14 tasks × 3 runs × cache on/off)
bash phase2/run_full_benchmark.sh 3
python3 phase2/aggregate.py
```

The `scripts/` directory contains numbered steps that can also be run individually.

## What's in here

```
.
├── run-phase1.sh            # one-shot Phase 1
├── scripts/                 # numbered Phase 1 steps (00..07, 99-cleanup)
├── configs/                 # prometheus.yml (generated)
├── fixtures/inbox/          # 5 sample emails for Phase 1
├── phase2/
│   ├── SCHEMA.md            # task definition format
│   ├── tasks/*.yaml         # 14 task definitions (6 OpenClaw + 8 Claude Code)
│   ├── fixtures/            # per-task fixtures (inbox-20, sample-repo, buggy-code, etc.)
│   ├── runner.py            # task runner (setup/run/metrics/teardown × N runs)
│   ├── aggregate.py         # produces summary.csv + report.md
│   └── run_full_benchmark.sh
└── results/                 # benchmark outputs (gitignored except summaries)
```

## Model

By default uses a locally quantized Qwen3.5-35B-A3B GPTQ-W4A16 (group_size=32). Replace
the `MODEL_PATH` env var or first positional arg in scripts to point at your model.

```bash
MODEL_PATH=/path/to/your/model bash run-phase1.sh
```

## Metrics collected

Per task run we capture from vLLM's Prometheus endpoint:

- TTFT (p50, p95)
- Prefill latency (p50, p95)
- Decode latency (p50, p95)
- Time between tokens (p50, p95)
- End-to-end latency (p50, p95)
- Prompt / generation token counts
- Prefix cache hit rate
- KV cache utilization
- Derived: prefill TPS, decode TPS

Plus agent-side metadata (turn count, tool calls, total cost).

## Phase 2 tasks at a glance

### OpenClaw (personal-assistant workloads)
- `oc_01_daily_briefing` — multi-file daily summary
- `oc_02_email_triage_x20` — classify 20 emails (prefix-cache stress test)
- `oc_03_web_research` — summarize 3 local HTML articles
- `oc_04_cron_heartbeat` — short periodic check task
- `oc_05_multi_skill` — multi-step orchestration (extract → draft → save)
- `oc_06_custom_skill_app` — **app build**: write a custom skill

### Claude Code (coding workloads)
- `cc_01_code_understand` — generate ARCHITECTURE.md from a repo
- `cc_02_small_modify` — add function + tests
- `cc_03_bug_fix` — find and fix a planted bug
- `cc_04_refactor_sync_async` — convert sync HTTP client to async
- `cc_05_cli_tool` — **app build**: CLI tool with subcommands
- `cc_06_flask_crud` — **app build**: Flask CRUD service
- `cc_07_textual_tui` — **app build**: Textual TUI dashboard
- `cc_08_react_todo` — **app build**: React TODO SPA

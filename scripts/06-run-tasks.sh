#!/usr/bin/env bash
# 06-run-tasks.sh — 依次跑 Phase 1 的两个 smoke test 任务，记录时间窗口
set -euo pipefail

BENCH_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RESULTS_DIR="$BENCH_DIR/results"
VLLM_PORT="${VLLM_PORT:-8000}"
PROM_PORT="${PROM_PORT:-9091}"
FIXTURE_DIR="$BENCH_DIR/fixtures/inbox"

mkdir -p "$RESULTS_DIR"

# ---- Helper: record time window ----
record_start() {
    date +%s
}

record_end() {
    local name="$1" start="$2"
    local end
    end=$(date +%s)
    echo "${name},${start},${end}" >> "$RESULTS_DIR/time_windows.csv"
    echo "Task '$name' completed: ${start} → ${end} ($((end - start))s)"
}

# Init time_windows.csv
echo "task,start_epoch,end_epoch" > "$RESULTS_DIR/time_windows.csv"

# ---- Verify vLLM is running ----
echo "Checking vLLM..."
curl -sf "http://localhost:${VLLM_PORT}/v1/models" >/dev/null || {
    echo "ERROR: vLLM not running on port $VLLM_PORT"
    exit 1
}
echo "✓ vLLM is up"

# ---- Verify Prometheus is running ----
echo "Checking Prometheus..."
curl -sf "http://localhost:${PROM_PORT}/-/healthy" >/dev/null || {
    echo "ERROR: Prometheus not running on port $PROM_PORT"
    exit 1
}
echo "✓ Prometheus is up"

echo ""
echo "========================================="
echo "  Task 1: OpenClaw — Email Triage"
echo "========================================="
T1_START=$(record_start)

openclaw agent --local --model vllm-local/qwen35 --session-id "bench-email-$(date +%s)" --json \
    -m "Read all email files in ${FIXTURE_DIR}/ directory. For each email, classify it as one of: [ACTION_REQUIRED], [FYI], or [SPAM]. Output a structured briefing with: 1) Summary of each email (1 line), 2) Classification, 3) Suggested priority (high/medium/low). Format as markdown." \
    2>&1 | tee "$RESULTS_DIR/openclaw-email-triage.log"

record_end "openclaw_email_triage" "$T1_START"

echo ""
echo "========================================="
echo "  Task 2: Claude Code — Add Function"
echo "========================================="
T2_START=$(record_start)

cd "$BENCH_DIR/cc-test-repo"
export ANTHROPIC_BASE_URL="http://localhost:${VLLM_PORT}"
export ANTHROPIC_API_KEY="dummy"
export ANTHROPIC_AUTH_TOKEN="dummy"
export ANTHROPIC_DEFAULT_OPUS_MODEL="qwen35"
export ANTHROPIC_DEFAULT_SONNET_MODEL="qwen35"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="qwen35"
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
export DISABLE_PROMPT_CACHING=1

claude -p \
    "Add a reverse_string function to utils.py that takes a string and returns it reversed. Add comprehensive tests for it in test_utils.py including edge cases (empty string, single char, unicode). Run the tests to verify they pass." \
    --allowedTools "Edit,Write,Bash,Read,Glob,Grep" \
    2>&1 | tee "$RESULTS_DIR/claude-code-add-function.log"

record_end "claude_code_add_function" "$T2_START"

echo ""
echo "========================================="
echo "  All tasks complete"
echo "========================================="
echo ""
echo "Time windows:"
cat "$RESULTS_DIR/time_windows.csv"
echo ""
echo "Next: run 07-collect-metrics.py to pull Prometheus data"

#!/usr/bin/env bash
# run_full_benchmark.sh — 跑完整 Phase 2: 14 tasks × N runs × cache(on,off)
#
# Steps:
#  1. Start vLLM with --enable-prefix-caching (cache ON)
#  2. Run all 14 tasks × N runs
#  3. Stop vLLM, restart WITHOUT --enable-prefix-caching (cache OFF)
#  4. Run all 14 tasks × N runs again
#  5. Aggregate metrics
#
# Usage: ./run_full_benchmark.sh [RUNS_PER_TASK]
#
set -euo pipefail

BENCH_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PHASE2_DIR="$BENCH_DIR/phase2"
RUNS_PER_TASK="${1:-3}"
MODEL_PATH="${MODEL_PATH:-/root/autodl-tmp/qwen35_quant_experiment/models/qwen35-a3b-r3-gptq-g32-w4a16/}"
VLLM_VENV="${VLLM_VENV:-/root/autodl-tmp/qwen35-quant-venv}"
VLLM_PORT="${VLLM_PORT:-8000}"
PROM_PORT="${PROM_PORT:-9091}"

log()  { echo -e "\033[1;36m[phase2]\033[0m $*"; }
warn() { echo -e "\033[1;33m[phase2]\033[0m $*"; }

stop_vllm() {
    log "Stopping vLLM..."
    pkill -f "vllm serve" 2>/dev/null || true
    sleep 5
    while pgrep -f "vllm serve" >/dev/null 2>&1; do
        sleep 2
    done
    log "vLLM stopped"
}

start_vllm() {
    local cache_flag="$1"   # "on" or "off"
    local flag_str=""
    [ "$cache_flag" = "on" ] && flag_str="--enable-prefix-caching" || flag_str="--no-enable-prefix-caching"
    log "Starting vLLM (prefix-caching $cache_flag)..."
    "$VLLM_VENV/bin/vllm" serve "$MODEL_PATH" \
        --served-model-name qwen35 \
        --tensor-parallel-size 1 \
        --max-model-len 65536 \
        --reasoning-parser qwen3 \
        --enable-auto-tool-choice \
        --tool-call-parser qwen3_coder \
        $flag_str \
        --quantization compressed-tensors \
        --dtype float16 \
        --port "$VLLM_PORT" \
        &> "$BENCH_DIR/results/vllm-cache-${cache_flag}.log" &
    log "vLLM PID: $!"
    # Wait for ready
    local waited=0
    while ! curl -sf "http://localhost:${VLLM_PORT}/v1/models" >/dev/null 2>&1; do
        sleep 5
        waited=$((waited + 5))
        if [ $waited -ge 600 ]; then
            warn "vLLM did not start within 600s"
            tail -30 "$BENCH_DIR/results/vllm-cache-${cache_flag}.log"
            exit 1
        fi
        printf "\r  Waiting for vLLM... %ds" $waited
    done
    echo ""
    log "vLLM ready ($waited s)"
}

run_all_tasks() {
    local cache_mode="$1"
    log "Running all tasks (cache=$cache_mode, $RUNS_PER_TASK runs each)"
    "$VLLM_VENV/bin/python" "$PHASE2_DIR/runner.py" \
        --task-glob "$PHASE2_DIR/tasks/*.yaml" \
        --runs "$RUNS_PER_TASK" \
        --cache-mode "$cache_mode" \
        2>&1 | tee -a "$BENCH_DIR/results/phase2-cache-${cache_mode}.log"
}

# ============================================================================
# Main
# ============================================================================
log "Phase 2 full benchmark starting"
log "  Runs per task: $RUNS_PER_TASK"
log "  Tasks: $(ls "$PHASE2_DIR/tasks/"*.yaml | wc -l)"
log "  Total runs: $((RUNS_PER_TASK * $(ls "$PHASE2_DIR/tasks/"*.yaml | wc -l) * 2))"

# Sanity: Prometheus & Grafana up?
curl -sf "http://localhost:${PROM_PORT}/-/healthy" >/dev/null || {
    warn "Prometheus not running on :$PROM_PORT. Run scripts/03-start-monitoring.sh first."
    exit 1
}
log "Prometheus is up"

# === Phase 2a: cache ON ===
stop_vllm
start_vllm "on"
sleep 10   # let metrics settle
run_all_tasks "on"

# === Phase 2b: cache OFF ===
stop_vllm
start_vllm "off"
sleep 10
run_all_tasks "off"

log "All runs complete. Now run aggregator: python3 $PHASE2_DIR/aggregate.py"

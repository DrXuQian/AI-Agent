#!/usr/bin/env bash
# run-phase1.sh — 一键跑通 Phase 1 全流程
# Usage: ./run-phase1.sh [MODEL_PATH] [MAX_MODEL_LEN] [TP_SIZE]
#
# 该脚本依次执行:
#   0. 环境检查
#   1. 安装依赖
#   2. 启动 vLLM (后台)
#   3. 启动 Prometheus + Grafana (后台)
#   4. 配置 OpenClaw
#   5. 配置 Claude Code 测试 repo
#   6. 跑两个 smoke test 任务
#   7. 采集 metrics
#
# 如需单独跑某步, 直接执行 scripts/0X-*.sh
set -euo pipefail

BENCH_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$BENCH_DIR"

MODEL_PATH="${1:-/root/autodl-tmp/qwen35_quant_experiment/models/qwen35-a3b-r3-gptq-g32-w4a16/}"
MAX_MODEL_LEN="${2:-65536}"
TP_SIZE="${3:-1}"
VLLM_PORT="${VLLM_PORT:-8000}"

echo "============================================"
echo "  Agent Bench — Phase 1"
echo "============================================"
echo "  Model:   $MODEL_PATH"
echo "  Context: $MAX_MODEL_LEN"
echo "  TP:      $TP_SIZE"
echo "  Port:    $VLLM_PORT"
echo "============================================"
echo ""

# ---- Step 0: Env check ----
echo ">>> Step 0: Environment check"
bash scripts/00-env-check.sh
echo ""

# ---- Step 1: Install deps ----
echo ">>> Step 1: Install dependencies"
bash scripts/01-install-deps.sh
echo ""

# ---- Step 2: Start vLLM (background) ----
echo ">>> Step 2: Starting vLLM..."
bash scripts/02-start-vllm.sh "$MODEL_PATH" "$MAX_MODEL_LEN" "$TP_SIZE" &
VLLM_PID=$!
echo "vLLM PID: $VLLM_PID"

# Wait for vLLM to be ready (model loading can take minutes)
echo "Waiting for vLLM to load model..."
MAX_WAIT=600
WAITED=0
while ! curl -sf "http://localhost:${VLLM_PORT}/v1/models" >/dev/null 2>&1; do
    sleep 5
    WAITED=$((WAITED + 5))
    if [ $WAITED -ge $MAX_WAIT ]; then
        echo "ERROR: vLLM did not start within ${MAX_WAIT}s"
        echo "Check results/vllm-server.log for errors"
        kill $VLLM_PID 2>/dev/null || true
        exit 1
    fi
    printf "\r  Waited %ds / %ds..." $WAITED $MAX_WAIT
done
echo ""
echo "✓ vLLM is ready (took ${WAITED}s)"
echo ""

# ---- Step 3: Start monitoring ----
echo ">>> Step 3: Starting Prometheus + Grafana"
bash scripts/03-start-monitoring.sh
echo ""

# ---- Step 4: Setup OpenClaw ----
echo ">>> Step 4: Configuring OpenClaw"
bash scripts/04-setup-openclaw.sh
echo ""

# ---- Step 5: Setup Claude Code ----
echo ">>> Step 5: Setting up Claude Code test repo"
bash scripts/05-setup-claudecode.sh
echo ""

# Wait a few seconds for Prometheus to scrape initial vLLM metrics
echo "Waiting 15s for Prometheus to scrape baseline metrics..."
sleep 15

# ---- Step 6: Run tasks ----
echo ">>> Step 6: Running tasks"
bash scripts/06-run-tasks.sh
echo ""

# ---- Step 7: Collect metrics ----
echo ">>> Step 7: Collecting metrics"
VLLM_VENV="${VLLM_VENV:-/root/autodl-tmp/qwen35-quant-venv}"
source "$VLLM_VENV/bin/activate"
python3 scripts/07-collect-metrics.py
deactivate
echo ""

echo "============================================"
echo "  Phase 1 Complete"
echo "============================================"
echo ""
echo "Results:    $BENCH_DIR/results/"
echo "Grafana:    http://localhost:3000 (admin/admin)"
echo "Prometheus: http://localhost:9090"
echo ""
echo "To stop all services: bash scripts/99-cleanup.sh"

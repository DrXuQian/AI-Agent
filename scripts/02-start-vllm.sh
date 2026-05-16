#!/usr/bin/env bash
# 02-start-vllm.sh — 启动 vLLM serving
# Usage: ./02-start-vllm.sh [MODEL_PATH] [MAX_MODEL_LEN] [TP_SIZE]
set -euo pipefail

BENCH_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VLLM_VENV="${VLLM_VENV:-/root/autodl-tmp/qwen35-quant-venv}"
source "$VLLM_VENV/bin/activate"

# ---- Configurable parameters ----
MODEL_PATH="${1:-/root/autodl-tmp/qwen35_quant_experiment/models/qwen35-a3b-r3-gptq-g32-w4a16/}"
MAX_MODEL_LEN="${2:-65536}"
TP_SIZE="${3:-1}"
PORT="${VLLM_PORT:-8000}"

# Auto-detect quantization from model config
if python3 -c "
import json, pathlib
cfg = json.loads((pathlib.Path('$MODEL_PATH') / 'config.json').read_text())
qcfg = cfg.get('quantization_config', {})
print(qcfg.get('quant_method', 'none'))
" 2>/dev/null | grep -q "compressed-tensors\|gptq"; then
    QUANT_FLAG="--quantization compressed-tensors"
    echo "Detected quantized model, using: $QUANT_FLAG"
else
    QUANT_FLAG=""
    echo "No quantization detected, using BF16"
fi

echo "Starting vLLM..."
echo "  Model:   $MODEL_PATH"
echo "  TP:      $TP_SIZE"
echo "  Context: $MAX_MODEL_LEN"
echo "  Port:    $PORT"
echo ""

exec vllm serve "$MODEL_PATH" \
    --served-model-name qwen35 \
    --tensor-parallel-size "$TP_SIZE" \
    --max-model-len "$MAX_MODEL_LEN" \
    --reasoning-parser qwen3 \
    --enable-auto-tool-choice \
    --tool-call-parser qwen3_coder \
    --enable-prefix-caching \
    $QUANT_FLAG \
    --dtype float16 \
    --port "$PORT" \
    2>&1 | tee "$BENCH_DIR/results/vllm-server.log"

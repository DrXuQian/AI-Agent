#!/usr/bin/env bash
# 00-env-check.sh — 检查目标机器环境是否满足要求
set -euo pipefail

echo "=== GPU ==="
nvidia-smi --query-gpu=name,memory.total,memory.free,count --format=csv,noheader 2>/dev/null || { echo "ERROR: nvidia-smi not found"; exit 1; }
GPU_COUNT=$(nvidia-smi -L | wc -l)
echo "GPU count: $GPU_COUNT"

echo ""
echo "=== Node.js ==="
node --version 2>/dev/null || { echo "ERROR: Node.js not found (need 24+)"; exit 1; }
NODE_MAJOR=$(node --version | sed 's/v//' | cut -d. -f1)
if [ "$NODE_MAJOR" -lt 24 ]; then
    echo "WARNING: Node $NODE_MAJOR detected, OpenClaw needs 24+. Run: npm install -g n && n 24"
fi

echo ""
echo "=== Python ==="
python3 --version 2>/dev/null || { echo "ERROR: Python3 not found"; exit 1; }

echo ""
echo "=== Disk ==="
df -h / | tail -1
df -h /root/autodl-tmp 2>/dev/null || true

echo ""
echo "=== VRAM estimate for Qwen3.5-35B-A3B ==="
VRAM_MB=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1)
echo "Total VRAM per GPU: ${VRAM_MB} MiB"
echo "Model W4A16 (~21GB) → KV headroom: ~$((VRAM_MB / 1024 - 21)) GB"
echo "Model BF16  (~67GB) → KV headroom: ~$((VRAM_MB / 1024 - 67)) GB"

if [ "$GPU_COUNT" -ge 4 ]; then
    echo "TP=4 available: BF16 fits with ~$((VRAM_MB * 4 / 1024 - 67)) GB KV headroom"
fi

echo ""
echo "=== Summary ==="
echo "GPU_COUNT=$GPU_COUNT"
echo "NODE_VERSION=$(node --version)"
echo "PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')"
echo "All checks passed."

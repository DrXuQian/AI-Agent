#!/usr/bin/env bash
# 99-cleanup.sh — 停止所有后台服务
set -euo pipefail

BENCH_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "Stopping services..."

# Kill by PID files
for pidfile in "$BENCH_DIR/results/.prometheus.pid" "$BENCH_DIR/results/.grafana.pid"; do
    if [ -f "$pidfile" ]; then
        pid=$(cat "$pidfile")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid"
            echo "Killed $(basename "$pidfile" .pid) (PID $pid)"
        fi
        rm -f "$pidfile"
    fi
done

# Kill vLLM if running
pkill -f "vllm serve" 2>/dev/null && echo "Killed vLLM" || true

# Kill LiteLLM if running
pkill -f "litellm" 2>/dev/null && echo "Killed LiteLLM" || true

echo "All services stopped."

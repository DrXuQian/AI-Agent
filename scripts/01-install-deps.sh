#!/usr/bin/env bash
# 01-install-deps.sh — 安装所有依赖 (vLLM, OpenClaw, Prometheus, Grafana)
set -euo pipefail

BENCH_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$BENCH_DIR"

echo "=== [1/5] vLLM ==="
if [ ! -d "$BENCH_DIR/vllm-env" ]; then
    python3 -m venv vllm-env
fi
source vllm-env/bin/activate
pip install -q vllm --extra-index-url https://wheels.vllm.ai/nightly
pip install -q prometheus_api_client requests
echo "vLLM version: $(python -c 'import vllm; print(vllm.__version__)')"
deactivate

echo ""
echo "=== [2/5] OpenClaw ==="
if ! command -v openclaw &>/dev/null; then
    npm install -g openclaw
fi
echo "OpenClaw: $(openclaw --version 2>/dev/null || echo 'installed')"

echo ""
echo "=== [3/5] Prometheus ==="
PROM_VERSION="3.4.1"
if [ ! -f "$BENCH_DIR/prometheus/prometheus" ]; then
    mkdir -p "$BENCH_DIR/prometheus"
    wget -qO- "https://github.com/prometheus/prometheus/releases/download/v${PROM_VERSION}/prometheus-${PROM_VERSION}.linux-amd64.tar.gz" \
        | tar xz --strip-components=1 -C "$BENCH_DIR/prometheus"
fi
echo "Prometheus: $("$BENCH_DIR/prometheus/prometheus" --version 2>&1 | head -1)"

echo ""
echo "=== [4/5] Grafana ==="
GRAFANA_VERSION="12.1.0"
if [ ! -f "$BENCH_DIR/grafana/bin/grafana" ] && [ ! -f "$BENCH_DIR/grafana/bin/grafana-server" ]; then
    mkdir -p "$BENCH_DIR/grafana"
    wget -qO- "https://dl.grafana.com/oss/release/grafana-${GRAFANA_VERSION}.linux-amd64.tar.gz" \
        | tar xz --strip-components=1 -C "$BENCH_DIR/grafana"
fi
GRAFANA_BIN="$BENCH_DIR/grafana/bin/grafana"
[ -f "$GRAFANA_BIN" ] || GRAFANA_BIN="$BENCH_DIR/grafana/bin/grafana-server"
echo "Grafana: $($GRAFANA_BIN -v 2>&1 | head -1)"

echo ""
echo "=== [5/5] LiteLLM (fallback proxy for Claude Code) ==="
source vllm-env/bin/activate
pip install -q 'litellm[proxy]' 2>/dev/null || echo "WARNING: litellm install failed, may not need it"
deactivate

echo ""
echo "All dependencies installed."

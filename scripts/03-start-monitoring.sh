#!/usr/bin/env bash
# 03-start-monitoring.sh — 启动 Prometheus + Grafana
set -euo pipefail

BENCH_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PROM_DIR="$BENCH_DIR/prometheus"
GRAFANA_DIR="$BENCH_DIR/grafana"
PROM_PORT="${PROM_PORT:-9091}"
GRAFANA_PORT="${GRAFANA_PORT:-3000}"

# ---- Write Prometheus config ----
cat > "$BENCH_DIR/configs/prometheus.yml" <<'EOF'
global:
  scrape_interval: 5s
  evaluation_interval: 5s

scrape_configs:
  - job_name: vllm
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: /metrics
EOF

# ---- Start Prometheus ----
echo "Starting Prometheus on :${PROM_PORT}..."
"$PROM_DIR/prometheus" \
    --config.file="$BENCH_DIR/configs/prometheus.yml" \
    --storage.tsdb.path="$BENCH_DIR/results/prometheus-data" \
    --web.listen-address=":${PROM_PORT}" \
    --storage.tsdb.retention.time=7d \
    &> "$BENCH_DIR/results/prometheus.log" &
PROM_PID=$!
echo "Prometheus PID: $PROM_PID"

# ---- Start Grafana ----
echo "Starting Grafana on :${GRAFANA_PORT}..."
GRAFANA_BIN="$GRAFANA_DIR/bin/grafana"
[ -f "$GRAFANA_BIN" ] || GRAFANA_BIN="$GRAFANA_DIR/bin/grafana-server"

# Grafana needs a homepath
"$GRAFANA_BIN" server \
    --homepath="$GRAFANA_DIR" \
    --config="$GRAFANA_DIR/conf/defaults.ini" \
    cfg:server.http_port=3000 \
    cfg:security.admin_password=admin \
    &> "$BENCH_DIR/results/grafana.log" &
GRAFANA_PID=$!
echo "Grafana PID: $GRAFANA_PID"

# ---- Save PIDs for cleanup ----
echo "$PROM_PID" > "$BENCH_DIR/results/.prometheus.pid"
echo "$GRAFANA_PID" > "$BENCH_DIR/results/.grafana.pid"

# ---- Wait and verify ----
sleep 3

if curl -sf http://localhost:${PROM_PORT}/-/healthy >/dev/null 2>&1; then
    echo "✓ Prometheus healthy"
else
    echo "✗ Prometheus not responding, check results/prometheus.log"
fi

if curl -sf http://localhost:${GRAFANA_PORT}/api/health >/dev/null 2>&1; then
    echo "✓ Grafana healthy (admin/admin at http://localhost:${GRAFANA_PORT})"
else
    echo "✗ Grafana not responding, check results/grafana.log"
fi

# ---- Auto-add Prometheus datasource to Grafana ----
sleep 2
curl -sf -X POST http://admin:admin@localhost:${GRAFANA_PORT}/api/datasources \
    -H "Content-Type: application/json" \
    -d '{
        "name": "Prometheus",
        "type": "prometheus",
        "url": "http://localhost:${PROM_PORT}",
        "access": "proxy",
        "isDefault": true
    }' >/dev/null 2>&1 && echo "✓ Grafana datasource configured" || echo "Datasource may already exist"

echo ""
echo "Monitoring started. To stop: kill $PROM_PID $GRAFANA_PID"
echo "Or run: ./scripts/99-cleanup.sh"

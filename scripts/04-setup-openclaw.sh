#!/usr/bin/env bash
# 04-setup-openclaw.sh — 配置 OpenClaw 连接本地 vLLM
set -euo pipefail

BENCH_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VLLM_URL="${VLLM_URL:-http://127.0.0.1:8000/v1}"
OPENCLAW_CONFIG_DIR="${HOME}/.openclaw"

# Initialize OpenClaw if no config exists
if [ ! -f "$OPENCLAW_CONFIG_DIR/openclaw.json" ]; then
    openclaw setup --non-interactive 2>/dev/null || true
fi

# Patch config via CLI (produces valid openclaw.json)
openclaw config patch --stdin <<PATCH
{
  "models": {
    "mode": "merge",
    "providers": {
      "vllm-local": {
        "baseUrl": "${VLLM_URL}",
        "apiKey": "sk-local",
        "api": "openai-completions",
        "timeoutSeconds": 300,
        "contextWindow": 65536,
        "maxTokens": 8192,
        "models": [
          {
            "id": "qwen35",
            "name": "Qwen3.5-35B-A3B via vLLM",
            "api": "openai-completions",
            "input": ["text"],
            "reasoning": true
          }
        ]
      }
    }
  },
  "agents": {
    "defaults": {
      "model": "vllm-local/qwen35"
    }
  }
}
PATCH

echo "OpenClaw config patched."
openclaw models status 2>&1 | head -5

# ---- Create fixture data for testing ----
FIXTURE_DIR="$BENCH_DIR/fixtures/inbox"
mkdir -p "$FIXTURE_DIR"

cat > "$FIXTURE_DIR/email1.txt" <<'EOF'
From: boss@company.com
Subject: Q1 review tomorrow 10am
Date: 2026-05-16

Hi team,
Please prepare the Q1 work summary report. We need to cover:
1. Key deliverables and completion status
2. Budget utilization
3. Headcount changes
4. Q2 priorities

Meeting is at 10am in Room 301. Bring printed copies.

Best,
Director Zhang
EOF

cat > "$FIXTURE_DIR/email2.txt" <<'EOF'
From: hr@company.com
Subject: Annual leave policy update
Date: 2026-05-15

Dear all,
Starting June 1, annual leave requests must be submitted 5 business days in advance.
Emergency leave remains at manager discretion. See attached policy document.

HR Team
EOF

cat > "$FIXTURE_DIR/email3.txt" <<'EOF'
From: spam@promo.xyz
Subject: LIMITED TIME OFFER - 90% OFF!!!
Date: 2026-05-16

CLICK HERE TO CLAIM YOUR PRIZE! You have been selected...
This is totally not spam. Act now before it's too late!!!
EOF

cat > "$FIXTURE_DIR/email4.txt" <<'EOF'
From: devops@company.com
Subject: Scheduled maintenance window - May 18 02:00-06:00
Date: 2026-05-15

Hi team,
We will be performing database migration and k8s cluster upgrade this Sunday.
Expected downtime: 2-4 hours. Please save all work before Friday EOD.
Rollback plan is documented in Confluence.

DevOps Team
EOF

cat > "$FIXTURE_DIR/email5.txt" <<'EOF'
From: alice@company.com
Subject: Re: Code review for PR #1234
Date: 2026-05-16

Hey, I left some comments on your PR. Main concern is the error handling
in the retry logic - we should add exponential backoff instead of fixed delay.
Can you update before the sprint ends?

Thanks,
Alice
EOF

echo ""
echo "Fixture emails created in $FIXTURE_DIR (5 emails)"

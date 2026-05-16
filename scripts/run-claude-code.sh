#!/usr/bin/env bash
# run-claude-code.sh — Launch Claude Code connected to local vLLM
# Usage: ./scripts/run-claude-code.sh [prompt]
set -euo pipefail

BENCH_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CC_TEST_DIR="$BENCH_DIR/cc-test-repo"
VLLM_PORT="${VLLM_PORT:-8000}"

cd "$CC_TEST_DIR"

export ANTHROPIC_BASE_URL="http://localhost:${VLLM_PORT}"
export ANTHROPIC_API_KEY="dummy"
export ANTHROPIC_AUTH_TOKEN="dummy"
export ANTHROPIC_DEFAULT_OPUS_MODEL="qwen35"
export ANTHROPIC_DEFAULT_SONNET_MODEL="qwen35"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="qwen35"
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
export DISABLE_PROMPT_CACHING=1

if [ $# -gt 0 ]; then
    echo "Running Claude Code with prompt: $*"
    claude --dangerously-skip-permissions -p "$*"
else
    echo "Starting Claude Code interactively..."
    claude
fi

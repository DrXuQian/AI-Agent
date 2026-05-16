#!/usr/bin/env bash
# 05-setup-claudecode.sh — 准备 Claude Code 测试 repo 和启动脚本
set -euo pipefail

BENCH_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CC_TEST_DIR="$BENCH_DIR/cc-test-repo"

# ---- Create test repo ----
if [ -d "$CC_TEST_DIR/.git" ]; then
    echo "Test repo already exists at $CC_TEST_DIR"
else
    mkdir -p "$CC_TEST_DIR"
    cd "$CC_TEST_DIR"
    git init
    git config user.email "bench@test.local"
    git config user.name "Bench"

    cat > utils.py <<'PYEOF'
"""Utility functions for the demo project."""


def add(a: int, b: int) -> int:
    """Return the sum of two numbers."""
    return a + b


def multiply(a: int, b: int) -> int:
    """Return the product of two numbers."""
    return a * b


def fibonacci(n: int) -> list[int]:
    """Return the first n Fibonacci numbers."""
    if n <= 0:
        return []
    if n == 1:
        return [0]
    seq = [0, 1]
    for _ in range(2, n):
        seq.append(seq[-1] + seq[-2])
    return seq
PYEOF

    cat > test_utils.py <<'PYEOF'
"""Tests for utility functions."""
import unittest
from utils import add, multiply, fibonacci


class TestAdd(unittest.TestCase):
    def test_positive(self):
        self.assertEqual(add(2, 3), 5)

    def test_negative(self):
        self.assertEqual(add(-1, -2), -3)

    def test_zero(self):
        self.assertEqual(add(0, 0), 0)


class TestMultiply(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(multiply(3, 4), 12)

    def test_zero(self):
        self.assertEqual(multiply(5, 0), 0)


class TestFibonacci(unittest.TestCase):
    def test_five(self):
        self.assertEqual(fibonacci(5), [0, 1, 1, 2, 3])

    def test_one(self):
        self.assertEqual(fibonacci(1), [0])

    def test_zero(self):
        self.assertEqual(fibonacci(0), [])


if __name__ == "__main__":
    unittest.main()
PYEOF

    git add .
    git commit -m "init: utils with add, multiply, fibonacci + tests"
    echo "Test repo created at $CC_TEST_DIR"
fi

# ---- Write Claude Code launch wrapper ----
cat > "$BENCH_DIR/scripts/run-claude-code.sh" <<'BASH'
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
BASH
chmod +x "$BENCH_DIR/scripts/run-claude-code.sh"

echo ""
echo "Claude Code setup complete."
echo "  Test repo: $CC_TEST_DIR"
echo "  Launch:    ./scripts/run-claude-code.sh"
echo "  With task: ./scripts/run-claude-code.sh 'add reverse_string function with tests'"

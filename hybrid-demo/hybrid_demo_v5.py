#!/usr/bin/env python3
"""
Hybrid agentic-coding demo v3 — squeezing the savings ceiling.

Changes over v2 (applied to BOTH arms so the comparison stays fair):
  - Prompt caching: system+tools cached, plus a moving breakpoint on the last
    message each turn -> conversation history is re-read at ~0.1x price.
  - Cache-aware cost meter (write=1.25x input price, read=0.1x input price).
  - Tighter information diet for the orchestrator: 5-line worker summaries,
    `pytest --tb=line`, and an instruction not to read whole files unless
    debugging requires it.

Arms:
  python3 hybrid_demo_v3.py                # hybrid (Fable 5 + Sonnet worker)
  python3 hybrid_demo_v3.py --no-delegate  # baseline (Fable 5 alone)
"""

import json
import os
import shutil
import subprocess
import sys

import anthropic

ORCHESTRATOR = "claude-fable-5"
WORKER = "claude-sonnet-4-6"
WORKSPACE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workspace_v5")

PRICE = {  # $ per 1M tokens (input, output)
    "claude-fable-5": (10.0, 50.0),
    "claude-sonnet-4-6": (3.0, 15.0),
}

# ----------------------------------------------------------------------------
# Cache-aware token accounting
# ----------------------------------------------------------------------------
class Meter:
    def __init__(self):
        self.stats = {}
        self.delegations = 0

    def add(self, model, usage):
        s = self.stats.setdefault(
            model, {"in": 0, "cache_w": 0, "cache_r": 0, "out": 0, "calls": 0})
        s["in"] += usage.input_tokens
        s["cache_w"] += getattr(usage, "cache_creation_input_tokens", 0) or 0
        s["cache_r"] += getattr(usage, "cache_read_input_tokens", 0) or 0
        s["out"] += usage.output_tokens
        s["calls"] += 1

    def cost(self, model):
        pin, pout = PRICE[model]
        s = self.stats[model]
        return (s["in"] * pin + s["cache_w"] * 1.25 * pin
                + s["cache_r"] * 0.1 * pin + s["out"] * pout) / 1e6

    def report(self, label):
        print("\n" + "=" * 70)
        print(f"TOKEN / COST REPORT  [{label}]")
        print("=" * 70)
        total = 0.0
        for model, s in self.stats.items():
            c = self.cost(model)
            total += c
            role = "ORCHESTRATOR" if model == ORCHESTRATOR else "WORKER"
            print(f"  [{role:12}] {model}")
            print(f"      calls={s['calls']}  in={s['in']}  cache_w={s['cache_w']}  "
                  f"cache_r={s['cache_r']}  out={s['out']}  cost=${c:.4f}")
        print("-" * 70)
        print(f"  delegations: {self.delegations}    TOTAL cost = ${total:.4f}")
        print("=" * 70)
        return total


meter = Meter()


def make_client():
    token_file = os.environ.get("CLAUDE_SESSION_INGRESS_TOKEN_FILE")
    if token_file and os.path.exists(token_file):
        return anthropic.Anthropic(
            auth_token=open(token_file).read().strip(),
            default_headers={"anthropic-beta": "oauth-2025-04-20"},
        )
    return anthropic.Anthropic()


client = make_client()

# ----------------------------------------------------------------------------
# Tools
# ----------------------------------------------------------------------------
def safe_path(rel):
    p = os.path.normpath(os.path.join(WORKSPACE, rel))
    if not p.startswith(WORKSPACE):
        raise ValueError(f"path escapes workspace: {rel}")
    return p


def run_worker(task: str, output_file: str | None) -> str:
    meter.delegations += 1
    print(f"\n  >>> delegate #{meter.delegations} -> {WORKER}"
          + (f"  [writes {output_file}]" if output_file else ""))
    print(f"      {task.strip().splitlines()[0][:88]}")
    # Out-of-band context sharing: the worker is local, so handing it the full
    # original task text costs the orchestrator nothing. The orchestrator only
    # needs to send its *delta* (which file + interface decisions).
    resp = client.messages.create(
        model=WORKER,
        max_tokens=4000,
        system=(
            "You are a focused coding worker on a local device. You can see the "
            "user's original project task (below) and ONE subtask from the "
            "orchestrator. Return ONLY the requested file content or text — no "
            "markdown fences, no commentary. Follow the orchestrator's interface "
            "decisions exactly; they override anything ambiguous in the task.\n\n"
            "=== ORIGINAL PROJECT TASK ===\n" + TASK
        ),
        messages=[{"role": "user", "content": task}],
    )
    meter.add(WORKER, resp.usage)
    text = "".join(b.text for b in resp.content if b.type == "text")
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        t = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        text = t + "\n"
    print(f"  <<< {len(text)} chars (in={resp.usage.input_tokens} out={resp.usage.output_tokens})")

    if output_file:
        p = safe_path(output_file)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)
        preview = "\n".join(text.splitlines()[:5])
        return (f"written to {output_file} ({len(text.splitlines())} lines). "
                f"Head:\n{preview}\n...")
    return text


def tool_write_file(path, content):
    p = safe_path(path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(content)
    return f"wrote {path} ({len(content)} chars)"


def tool_read_file(path):
    p = safe_path(path)
    if not os.path.exists(p):
        return f"ERROR: {path} does not exist"
    content = open(p).read()
    return content if len(content) < 12000 else content[:12000] + "\n...(truncated)"


def tool_run_command(command):
    print(f"  $ {command}")
    try:
        r = subprocess.run(command, shell=True, cwd=WORKSPACE,
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        if len(out) > 5000:
            out = out[:2500] + "\n...(truncated)...\n" + out[-2500:]
        return f"exit code {r.returncode}\n{out}"
    except subprocess.TimeoutExpired:
        return "ERROR: command timed out after 120s"


TOOLS = [
    {
        "name": "delegate_to_local",
        "description": (
            "Hand off a coding subtask to the cheap on-device local model. The "
            "worker AUTOMATICALLY sees the user's full original task text, so do "
            "NOT restate it — send only: which file to produce + the interface "
            "decisions you've made that the worker can't infer (exact token "
            "format, AST node shapes, etc.). Keep delegation messages SHORT. "
            "Always pass output_file so code never enters your context; you get "
            "a 5-line summary back. Do NOT delegate architecture or cross-module "
            "debugging."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {"type": "string"},
                "output_file": {"type": "string"},
            },
            "required": ["task"],
        },
    },
    {
        "name": "write_file",
        "description": "Write a workspace file yourself (small files or surgical fixes).",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a workspace file. Expensive for you — only when debugging requires it.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "run_command",
        "description": "Run a shell command in the workspace. For tests prefer 'python -m pytest -q --tb=line'.",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
]

SYSTEM_HYBRID = (
    "You are the orchestrator of a hybrid coding setup: a powerful but expensive "
    "cloud model paired with a cheap on-device local model reachable via "
    "delegate_to_local. You also have a workspace: write_file / read_file / "
    "run_command.\n\n"
    "Cost discipline (your tokens are 10x the worker's):\n"
    "- YOU own architecture, interface specs, decomposition, verification, and "
    "debugging decisions. Keep your own prose minimal.\n"
    "- DELEGATE every file implementation and every test file, always with "
    "output_file so code never enters your context. The worker already sees "
    "the user's original task — your delegation message should be a few lines "
    "of interface decisions only, never a restated spec.\n"
    "- Verify with 'python -m pytest -q --tb=line'. On failures: read only the "
    "minimal lines needed (or re-run with -k pattern), then either apply a tiny "
    "surgical fix with write_file or re-delegate that one file with a corrected, "
    "more explicit spec.\n"
    "- Delegate ALL files (modules AND tests) as parallel tool calls in your "
    "VERY FIRST turn — they are independent once you fix the interfaces.\n"
    "- Never paste file contents into your messages. Write no prose between "
    "tool calls. Final message: a report of AT MOST 4 short lines."
)

SYSTEM_BASELINE = (
    "You are a coding agent with a workspace: write_file / read_file / "
    "run_command. Build what the user asks, verify with "
    "'python -m pytest -q --tb=line', and fix failures until green. "
    "Write no prose between tool calls. Final message: a report of AT MOST "
    "8 short lines — no file contents."
)


def run_orchestrator(task: str, system: str, tools: list):
    # Cache the static prefix (tools+system). Moving breakpoint on last message.
    system_blocks = [{"type": "text", "text": system,
                      "cache_control": {"type": "ephemeral"}}]
    messages = [{"role": "user", "content": [
        {"type": "text", "text": task}]}]
    print("=" * 70)
    print(f"ORCHESTRATOR ({ORCHESTRATOR}) starting")
    print("=" * 70)

    for turn in range(1, 31):
        # Move the conversation cache breakpoint to the latest message.
        for m in messages:
            for blk in (m["content"] if isinstance(m["content"], list) else []):
                if isinstance(blk, dict):
                    blk.pop("cache_control", None)
        last = messages[-1]["content"]
        if isinstance(last, list) and last and isinstance(last[-1], dict):
            last[-1]["cache_control"] = {"type": "ephemeral"}

        resp = client.messages.create(
            model=ORCHESTRATOR,
            max_tokens=8000,
            output_config={"effort": "low"},
            system=system_blocks,
            tools=tools,
            messages=messages,
        )
        meter.add(ORCHESTRATOR, resp.usage)

        for b in resp.content:
            if b.type == "text" and b.text.strip():
                print(f"\n  [orchestrator t{turn}] {b.text.strip()[:400]}")

        if resp.stop_reason == "refusal":
            return "(orchestrator refused)"
        if resp.stop_reason != "tool_use":
            return "".join(b.text for b in resp.content if b.type == "text")

        # Echo assistant content back verbatim (keep thinking blocks intact).
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for b in resp.content:
            if b.type != "tool_use":
                continue
            try:
                if b.name == "delegate_to_local":
                    out = run_worker(b.input["task"], b.input.get("output_file"))
                elif b.name == "write_file":
                    out = tool_write_file(b.input["path"], b.input["content"])
                elif b.name == "read_file":
                    out = tool_read_file(b.input["path"])
                elif b.name == "run_command":
                    out = tool_run_command(b.input["command"])
                else:
                    out = f"unknown tool {b.name}"
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": out})
            except Exception as e:
                results.append({"type": "tool_result", "tool_use_id": b.id,
                                "content": f"ERROR: {e}", "is_error": True})
        messages.append({"role": "user", "content": results})

    return "(stopped: hit turn limit)"


TASK = """\
Build a small expression-language interpreter called `calclang` in this workspace.

Modules (package directory `calclang/` with __init__.py):
1. calclang/tokenizer.py — tokenize(source: str) -> list of tokens.
   Supports: floats/ints, identifiers, + - * / % ^ ( ) = , and the keywords
   handled naturally as identifiers. Raises CalcSyntaxError on illegal chars.
2. calclang/parser.py — parse(tokens) -> AST. Recursive descent with correct
   precedence (^ right-assoc > unary minus > * / % > + -), parentheses,
   function calls like min(1, 2, 3), and assignment statements `x = expr`.
3. calclang/evaluator.py — Evaluator class with .eval(source: str) -> float|None.
   Keeps a variable environment across calls; assignments return None and store
   the value; expressions return the float result. Builtin functions: min, max,
   abs, sqrt, pow. Undefined variable -> CalcNameError.
4. calclang/errors.py — CalcSyntaxError, CalcNameError (both ValueError subclasses).
5. calclang/repl.py — main() REPL: reads lines, prints results, 'quit' exits.
   Must be importable without running.

Tests (pytest, in tests/):
- tests/test_tokenizer.py, tests/test_parser.py, tests/test_evaluator.py
- Cover: precedence (2+3*4=14, 2^3^2=512, -2^2=-4), parens, variables persisting
  across eval calls, function calls, division by zero -> ZeroDivisionError,
  syntax errors, undefined names.

Definition of done: `python -m pytest -q` passes in the workspace with ALL tests
green, and `echo "1+2*3" | python -m calclang.repl` style import works.
Finish with a short report (no file contents)."""


if __name__ == "__main__":
    baseline = "--no-delegate" in sys.argv
    if baseline:
        WORKSPACE = WORKSPACE + "_baseline"
        tools = [t for t in TOOLS if t["name"] != "delegate_to_local"]
        system = SYSTEM_BASELINE
        label = "V5 BASELINE (effort=low)"
        print("*** BASELINE MODE ***")
    else:
        tools = TOOLS
        system = SYSTEM_HYBRID
        label = "V5 HYBRID (effort=low, max compression)"
    if os.path.exists(WORKSPACE):
        shutil.rmtree(WORKSPACE)
    os.makedirs(WORKSPACE)
    final = run_orchestrator(TASK, system, tools)
    print("\n" + "=" * 70)
    print("ORCHESTRATOR FINAL REPORT")
    print("=" * 70)
    print(final)
    meter.report(label)

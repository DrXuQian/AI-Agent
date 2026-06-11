#!/usr/bin/env python3
"""
Hybrid agentic-coding demo v2 — complex multi-file task with real verification.

Upgrades over v1:
  - Complex task with an interdependency chain (tokenizer -> parser -> evaluator
    -> REPL), so the orchestrator must spec interfaces before delegating.
  - Worker output is written DIRECTLY to files in a workspace; the orchestrator
    only receives a short summary. This kills the v1 cost sink where the
    orchestrator re-transcribed worker code into its own expensive output tokens.
  - The orchestrator can run real commands (pytest) in the workspace to verify,
    diagnose failures, and delegate fixes.

Roles:
  ORCHESTRATOR = Claude Fable 5    (plans, specs interfaces, verifies, fixes)
  WORKER       = Claude Sonnet 4.6 (stands in for the on-device small model)
"""

import json
import os
import shutil
import subprocess
import sys

import anthropic

ORCHESTRATOR = "claude-fable-5"
WORKER = "claude-sonnet-4-6"
WORKSPACE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workspace_v2")

PRICE = {  # $ per 1M tokens (input, output)
    "claude-fable-5": (10.0, 50.0),
    "claude-sonnet-4-6": (3.0, 15.0),
}

# ----------------------------------------------------------------------------
# Token accounting
# ----------------------------------------------------------------------------
class Meter:
    def __init__(self):
        self.stats = {}
        self.delegations = 0

    def add(self, model, usage):
        s = self.stats.setdefault(model, {"in": 0, "out": 0, "calls": 0})
        s["in"] += usage.input_tokens + getattr(usage, "cache_creation_input_tokens", 0) \
                   + getattr(usage, "cache_read_input_tokens", 0)
        s["out"] += usage.output_tokens
        s["calls"] += 1

    def cost(self, model):
        pin, pout = PRICE[model]
        s = self.stats[model]
        return s["in"] / 1e6 * pin + s["out"] / 1e6 * pout

    def report(self):
        print("\n" + "=" * 68)
        print("TOKEN / COST REPORT")
        print("=" * 68)
        total = 0.0
        for model, s in self.stats.items():
            c = self.cost(model)
            total += c
            role = "ORCHESTRATOR" if model == ORCHESTRATOR else "WORKER"
            print(f"  [{role:12}] {model}")
            print(f"      calls={s['calls']}  in={s['in']:>7}  out={s['out']:>7}  cost=${c:.4f}")
        print("-" * 68)
        print(f"  delegations to worker: {self.delegations}")
        print(f"  TOTAL cost = ${total:.4f}")
        if WORKER in self.stats:
            w = self.stats[WORKER]
            pin, pout = PRICE[ORCHESTRATOR]
            as_orch = w["in"] / 1e6 * pin + w["out"] / 1e6 * pout
            saved = as_orch - self.cost(WORKER)
            print(f"  offloaded {w['in']+w['out']} worker tokens; same tokens on the "
                  f"orchestrator: ${as_orch:.4f} (delegation saved ${saved:.4f})")
        print("=" * 68)


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
    """Run one subtask on the worker; optionally write its output straight to a file."""
    meter.delegations += 1
    head = task.strip().splitlines()[0][:88]
    print(f"\n  >>> delegate #{meter.delegations} -> {WORKER}"
          + (f"  [writes {output_file}]" if output_file else ""))
    print(f"      {head}")
    resp = client.messages.create(
        model=WORKER,
        max_tokens=4000,
        system=(
            "You are a focused coding worker on a local device. You receive ONE "
            "self-contained task with full context (you cannot see anything else). "
            "Return ONLY the requested file content or text — no markdown fences, "
            "no commentary before or after. Follow the given interface spec exactly."
        ),
        messages=[{"role": "user", "content": task}],
    )
    meter.add(WORKER, resp.usage)
    text = "".join(b.text for b in resp.content if b.type == "text")
    # Strip accidental code fences.
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines[-1].strip() == "```":
            t = "\n".join(lines[1:-1])
        else:
            t = "\n".join(lines[1:])
        text = t + "\n"
    print(f"  <<< {len(text)} chars (worker in={resp.usage.input_tokens} "
          f"out={resp.usage.output_tokens})")

    if output_file:
        p = safe_path(output_file)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)
        preview = "\n".join(text.splitlines()[:12])
        return (f"Worker output written to {output_file} "
                f"({len(text)} chars, {len(text.splitlines())} lines).\n"
                f"First lines:\n{preview}\n...\n"
                f"(Use read_file to inspect in full, run_command to verify.)")
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
        if len(out) > 6000:
            out = out[:3000] + "\n...(truncated)...\n" + out[-3000:]
        return f"exit code {r.returncode}\n{out}"
    except subprocess.TimeoutExpired:
        return "ERROR: command timed out after 120s"


TOOLS = [
    {
        "name": "delegate_to_local",
        "description": (
            "Hand off a SIMPLE, self-contained coding subtask to the cheaper "
            "on-device local model. The worker sees ONLY your task text — include "
            "the full interface spec, exact function/class signatures, data formats, "
            "and acceptance criteria it must follow. If output_file is given, the "
            "worker's raw output is written directly to that file and you get only "
            "a short summary back — this is the cheap path; prefer it for code "
            "files. Do NOT delegate architecture decisions, interface design, or "
            "debugging that requires whole-project context."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {"type": "string",
                         "description": "Fully self-contained instruction + context."},
                "output_file": {"type": "string",
                                "description": "Workspace-relative path to write the worker's output to."},
            },
            "required": ["task"],
        },
    },
    {
        "name": "write_file",
        "description": "Write a file in the workspace yourself (for small files, specs, or surgical fixes).",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a workspace file.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "run_command",
        "description": "Run a shell command in the workspace (e.g. 'python -m pytest -q', 'ls').",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
]

SYSTEM = (
    "You are the orchestrator of a hybrid coding setup: a powerful but expensive "
    "cloud model paired with a cheap on-device local model reachable via "
    "delegate_to_local. You also have a real workspace with write_file / read_file "
    "/ run_command.\n\n"
    "Cost strategy:\n"
    "- YOU own: architecture, interface specs, task decomposition, integration, "
    "verification, and debugging decisions.\n"
    "- DELEGATE: implementation of individual files once their interface is fully "
    "specified, test writing against a given spec, and mechanical fixes. Always "
    "pass output_file so code never flows through your expensive context.\n"
    "- Verify with run_command (pytest). If tests fail, diagnose from the failure "
    "output; apply small surgical fixes yourself with write_file/read_file, or "
    "re-delegate a file with a corrected spec if it needs a rewrite.\n"
    "- Independent subtasks: delegate them in ONE turn (parallel tool calls).\n"
    "- Do NOT paste full file contents into your messages. Your final message "
    "should be a short report: what was built, test results, and design notes."
)


def run_orchestrator(task: str):
    messages = [{"role": "user", "content": task}]
    print("=" * 68)
    print(f"ORCHESTRATOR ({ORCHESTRATOR}) starting")
    print("=" * 68)

    for turn in range(1, 31):
        resp = client.messages.create(
            model=ORCHESTRATOR,
            max_tokens=8000,
            system=SYSTEM,
            tools=TOOLS,
            messages=messages,
        )
        meter.add(ORCHESTRATOR, resp.usage)

        for b in resp.content:
            if b.type == "text" and b.text.strip():
                print(f"\n  [orchestrator t{turn}] {b.text.strip()[:500]}")

        if resp.stop_reason == "refusal":
            return "(orchestrator refused)"
        if resp.stop_reason != "tool_use":
            return "".join(b.text for b in resp.content if b.type == "text")

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
    if "--no-delegate" in sys.argv:
        # Baseline arm: same task, same workspace tools, but no worker available.
        WORKSPACE = WORKSPACE + "_baseline"
        TOOLS = [t for t in TOOLS if t["name"] != "delegate_to_local"]
        SYSTEM = (
            "You are a coding agent with a real workspace: write_file / read_file / "
            "run_command. Build what the user asks, verify with run_command (pytest), "
            "and fix failures until green. Your final message should be a short "
            "report: what was built, test results, design notes — no file contents."
        )
        print("*** BASELINE MODE: no delegation, orchestrator does everything ***")
    if os.path.exists(WORKSPACE):
        shutil.rmtree(WORKSPACE)
    os.makedirs(WORKSPACE)
    final = run_orchestrator(TASK)
    print("\n" + "=" * 68)
    print("ORCHESTRATOR FINAL REPORT")
    print("=" * 68)
    print(final)
    meter.report()

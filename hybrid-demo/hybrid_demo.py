#!/usr/bin/env python3
"""
Hybrid agentic-coding demo.

Architecture:
  - ORCHESTRATOR  = Claude Fable 5  (the "cloud brain": plans, decomposes, assembles)
  - WORKER        = Claude Sonnet 4.6 (stands in for the on-device small model:
                    executes simple, self-contained, decomposed subtasks)

The orchestrator is given a `delegate_to_local` tool and told a cheaper local
worker exists. It decides what to hand off. We meter token usage on BOTH sides
separately so we can see how much "expensive" orchestrator token spend the
delegation actually saves.

Auth: uses the Claude Code session token (Authorization: Bearer + oauth beta header).
"""

import json
import os
import sys

import anthropic

ORCHESTRATOR = "claude-fable-5"
WORKER = "claude-sonnet-4-6"

# $ per 1M tokens (input, output) — from the model catalog.
PRICE = {
    "claude-fable-5": (10.0, 50.0),
    "claude-sonnet-4-6": (3.0, 15.0),
}

# ----------------------------------------------------------------------------
# Token accounting
# ----------------------------------------------------------------------------
class Meter:
    def __init__(self):
        # model -> {"in": int, "out": int, "calls": int}
        self.stats = {}

    def add(self, model, usage):
        s = self.stats.setdefault(model, {"in": 0, "out": 0, "calls": 0})
        s["in"] += usage.input_tokens + getattr(usage, "cache_creation_input_tokens", 0)
        s["out"] += usage.output_tokens
        s["calls"] += 1

    def cost(self, model):
        pin, pout = PRICE[model]
        s = self.stats[model]
        return s["in"] / 1e6 * pin + s["out"] / 1e6 * pout

    def report(self):
        print("\n" + "=" * 64)
        print("TOKEN / COST REPORT")
        print("=" * 64)
        total = 0.0
        for model, s in self.stats.items():
            c = self.cost(model)
            total += c
            role = "ORCHESTRATOR" if model == ORCHESTRATOR else "WORKER"
            print(f"  [{role:12}] {model}")
            print(f"      calls={s['calls']}  in={s['in']:>6}  out={s['out']:>6}  cost=${c:.5f}")
        print("-" * 64)
        print(f"  TOTAL cost = ${total:.5f}")
        # Counterfactual: what if the orchestrator had done ALL the tokens itself?
        if WORKER in self.stats:
            w = self.stats[WORKER]
            pin, pout = PRICE[ORCHESTRATOR]
            as_orch = w["in"] / 1e6 * pin + w["out"] / 1e6 * pout
            saved = as_orch - self.cost(WORKER)
            print(f"  Worker did {w['in']+w['out']} tokens. Same tokens on the "
                  f"orchestrator would cost ${as_orch:.5f}")
            print(f"  -> delegation saved ${saved:.5f} on those tokens "
                  f"({saved/as_orch*100:.0f}% cheaper for the offloaded work)")
        print("=" * 64)


meter = Meter()


def make_client():
    token_file = os.environ.get("CLAUDE_SESSION_INGRESS_TOKEN_FILE")
    if token_file and os.path.exists(token_file):
        token = open(token_file).read().strip()
        return anthropic.Anthropic(
            auth_token=token,
            default_headers={"anthropic-beta": "oauth-2025-04-20"},
        )
    # Fall back to a normal API key if present.
    return anthropic.Anthropic()


client = make_client()


# ----------------------------------------------------------------------------
# The worker (local small model stand-in)
# ----------------------------------------------------------------------------
def run_worker(task: str) -> str:
    """Execute one self-contained subtask on the cheap worker model."""
    print(f"\n  >>> DELEGATING to worker ({WORKER}):")
    print(f"      {task.strip().splitlines()[0][:90]}...")
    resp = client.messages.create(
        model=WORKER,
        max_tokens=2000,
        system=(
            "You are a focused coding worker. You receive one small, self-contained "
            "task and return ONLY the requested code or text. No explanation, no "
            "markdown fences unless asked. Be precise and complete."
        ),
        messages=[{"role": "user", "content": task}],
    )
    meter.add(WORKER, resp.usage)
    text = "".join(b.text for b in resp.content if b.type == "text")
    print(f"  <<< worker returned {len(text)} chars "
          f"(in={resp.usage.input_tokens} out={resp.usage.output_tokens})")
    return text


# ----------------------------------------------------------------------------
# Orchestrator tool definition
# ----------------------------------------------------------------------------
DELEGATE_TOOL = {
    "name": "delegate_to_local",
    "description": (
        "Hand off a SIMPLE, self-contained subtask to the cheaper on-device local "
        "model to save cost. Good candidates: writing a single well-specified "
        "function, writing unit tests for a given signature, boilerplate, mechanical "
        "edits, summarizing long output. Provide a fully self-contained task "
        "description with any context the worker needs and a clear acceptance "
        "criterion — the worker has NO access to the rest of the conversation. "
        "Do NOT delegate architecture decisions or final assembly."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "Self-contained instruction + context for the worker.",
            }
        },
        "required": ["task"],
    },
}

SYSTEM = (
    "You are the orchestrator of a hybrid coding setup. You are a powerful cloud "
    "model, but your tokens are expensive. You have access to a cheaper LOCAL small "
    "model via the `delegate_to_local` tool. Strategy: do the planning, decomposition, "
    "and final assembly yourself, but delegate simple, well-specified, self-contained "
    "subtasks (e.g. writing an individual function body or a block of unit tests) to "
    "the local model to save cost. Each delegated task must be fully self-contained. "
    "When all work is done, output the final deliverable as complete files in your "
    "own message."
)


def run_orchestrator(task: str):
    messages = [{"role": "user", "content": task}]
    print("=" * 64)
    print(f"ORCHESTRATOR ({ORCHESTRATOR}) starting task")
    print("=" * 64)
    print(task.strip())

    for turn in range(12):
        resp = client.messages.create(
            model=ORCHESTRATOR,
            max_tokens=8000,
            system=SYSTEM,
            tools=[DELEGATE_TOOL],
            messages=messages,
        )
        meter.add(ORCHESTRATOR, resp.usage)

        # Show any orchestrator text this turn.
        for b in resp.content:
            if b.type == "text" and b.text.strip():
                print(f"\n  [orchestrator] {b.text.strip()[:400]}")

        if resp.stop_reason != "tool_use":
            # Done — return final assembled output.
            final = "".join(b.text for b in resp.content if b.type == "text")
            return final

        # Echo assistant turn back verbatim (thinking blocks included).
        messages.append({"role": "assistant", "content": resp.content})

        # Run each delegated tool call.
        results = []
        for b in resp.content:
            if b.type == "tool_use" and b.name == "delegate_to_local":
                out = run_worker(b.input["task"])
                results.append({
                    "type": "tool_result",
                    "tool_use_id": b.id,
                    "content": out,
                })
        messages.append({"role": "user", "content": results})

    return "(stopped: hit turn limit)"


if __name__ == "__main__":
    task = (
        "Build a small Python module `stringutils.py` with these three functions, "
        "each with a clear docstring:\n"
        "  1. slugify(text) -> str   : lowercase, spaces->hyphens, strip non-alphanumerics\n"
        "  2. truncate(text, n) -> str : truncate to n chars, append '...' if cut\n"
        "  3. word_count(text) -> dict : map each lowercased word to its frequency\n"
        "Also write a pytest test file `test_stringutils.py` covering all three.\n"
        "Deliver both complete files."
    )
    final = run_orchestrator(task)
    print("\n" + "=" * 64)
    print("FINAL DELIVERABLE")
    print("=" * 64)
    print(final)
    meter.report()

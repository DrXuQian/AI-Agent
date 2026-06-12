#!/usr/bin/env python3
"""
Local-first architecture for SWE-bench: the free local worker attempts the
whole fix on its own agent loop; the expensive cloud model only REVIEWS the
result (verify, accept, or intervene). Under the AI-station assumption
(local compute is free), cloud spend = review cost only.

  python3 swebench_localfirst.py <instance_id>

Stage 1 (free):  Sonnet agent loop with read/write/run tools fixes the issue.
Stage 2 (cloud): Fable 5 reviews the diff, runs targeted verification, and
                 fixes anything wrong — delegating rework back to the worker
                 where useful.
"""

import json
import os
import subprocess
import sys

import anthropic

ORCHESTRATOR = "claude-fable-5"
WORKER = "claude-sonnet-4-6"
HERE = os.path.dirname(os.path.abspath(__file__))

PRICE = {
    "claude-fable-5": (10.0, 50.0),
    "claude-sonnet-4-6": (3.0, 15.0),
}


class Meter:
    def __init__(self):
        self.stats = {}

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

    def summary(self):
        out = {m: dict(s, cost=round(self.cost(m), 4)) for m, s in self.stats.items()}
        out["cloud_cost"] = round(self.cost(ORCHESTRATOR), 4) if ORCHESTRATOR in self.stats else 0.0
        return out


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
WORKSPACE = None
ISSUE = None


def safe_path(rel):
    p = os.path.normpath(os.path.join(WORKSPACE, rel))
    if not p.startswith(WORKSPACE):
        raise ValueError(f"path escapes workspace: {rel}")
    return p


def tool_write_file(path, content):
    p = safe_path(path)
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with open(p, "w") as f:
        f.write(content)
    return f"wrote {path} ({len(content)} chars)"


def tool_read_file(path, cap=20000):
    p = safe_path(path)
    if not os.path.exists(p):
        return f"ERROR: {path} does not exist"
    c = open(p).read()
    return c if len(c) <= cap else c[:cap] + "\n...(truncated)"


def tool_run_command(command):
    print(f"  $ {command[:100]}")
    try:
        r = subprocess.run(command, shell=True, cwd=WORKSPACE,
                           capture_output=True, text=True, timeout=300)
        out = (r.stdout + r.stderr).strip()
        if len(out) > 5000:
            out = out[:2500] + "\n...(truncated)...\n" + out[-2500:]
        return f"exit code {r.returncode}\n{out}"
    except subprocess.TimeoutExpired:
        return "ERROR: command timed out after 300s"


BASE_TOOLS = [
    {"name": "write_file",
     "description": "Write a workspace file.",
     "input_schema": {"type": "object",
                      "properties": {"path": {"type": "string"},
                                     "content": {"type": "string"}},
                      "required": ["path", "content"]}},
    {"name": "read_file",
     "description": "Read a workspace file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}},
                      "required": ["path"]}},
    {"name": "run_command",
     "description": "Run a shell command in the repo root. Use '.venv/bin/python -m pytest' for tests.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}},
                      "required": ["command"]}},
]


def dispatch(b):
    if b.name == "write_file":
        return tool_write_file(b.input["path"], b.input["content"])
    if b.name == "read_file":
        return tool_read_file(b.input["path"])
    if b.name == "run_command":
        return tool_run_command(b.input["command"])
    return f"unknown tool {b.name}"


def agent_loop(model, system, task, max_turns, label, extra_kwargs=None):
    system_blocks = [{"type": "text", "text": system,
                      "cache_control": {"type": "ephemeral"}}]
    messages = [{"role": "user", "content": [{"type": "text", "text": task}]}]
    for turn in range(1, max_turns + 1):
        for m in messages:
            for blk in (m["content"] if isinstance(m["content"], list) else []):
                if isinstance(blk, dict):
                    blk.pop("cache_control", None)
        last = messages[-1]["content"]
        if isinstance(last, list) and last and isinstance(last[-1], dict):
            last[-1]["cache_control"] = {"type": "ephemeral"}

        resp = client.messages.create(
            model=model, max_tokens=8000, system=system_blocks,
            tools=BASE_TOOLS, messages=messages, **(extra_kwargs or {}))
        meter.add(model, resp.usage)

        for b in resp.content:
            if b.type == "text" and b.text.strip():
                print(f"\n  [{label} t{turn}] {b.text.strip()[:300]}")

        if resp.stop_reason == "refusal":
            return "(refused)"
        if resp.stop_reason != "tool_use":
            return "".join(b.text for b in resp.content if b.type == "text")

        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for b in resp.content:
            if b.type != "tool_use":
                continue
            try:
                results.append({"type": "tool_result", "tool_use_id": b.id,
                                "content": dispatch(b)})
            except Exception as e:
                results.append({"type": "tool_result", "tool_use_id": b.id,
                                "content": f"ERROR: {e}", "is_error": True})
        messages.append({"role": "user", "content": results})
    return "(hit turn limit)"


WORKER_SYSTEM = (
    "You are a capable local coding agent fixing a bug in a real repository "
    "checkout (project installed in .venv). Workflow: reproduce the issue if "
    "practical, localize via grep/read, apply a minimal targeted fix, verify "
    "with '.venv/bin/python -m pytest <relevant test file> -q --tb=short' and "
    "your own reproduction. Do NOT modify files under tests/ or testing/ "
    "(temporary repro scripts in the repo root are fine; delete them when done). "
    "Final message: root cause, change made, verification evidence (max 10 lines)."
)

REVIEWER_SYSTEM = (
    "You are the expensive cloud reviewer in a hybrid setup. A free local model "
    "has already attempted a bug fix; its diff and report are in the user "
    "message. Your tokens cost 10x — be surgical:\n"
    "- Judge the diff against the issue. Verify by running targeted tests "
    "('.venv/bin/python -m pytest <file> -q --tb=short') and, if cheap, a quick "
    "reproduction of the issue's scenario.\n"
    "- If correct and complete: accept. Do not rewrite working code.\n"
    "- If wrong/incomplete: fix it yourself with minimal surgical edits.\n"
    "- NEVER modify files under tests/ or testing/.\n"
    "- No prose between tool calls. Final message: VERDICT (accepted | fixed) "
    "+ at most 6 short lines."
)


def reset_repo(repo_dir, base_commit):
    subprocess.run(["git", "checkout", "-qf", base_commit], cwd=repo_dir, check=True)
    subprocess.run(["git", "clean", "-qfd", "-e", ".venv"], cwd=repo_dir, check=True)


def main():
    global WORKSPACE, ISSUE
    iid = sys.argv[1]
    inst = next(r for r in json.load(open(os.path.join(HERE, "candidates.json")))
                if r["instance_id"] == iid)
    WORKSPACE = os.path.join(HERE, "repos", iid)
    ISSUE = inst["problem_statement"]
    reset_repo(WORKSPACE, inst["base_commit"])

    print(f"### {iid} [local-first] ###")

    # ---- Stage 1: free local attempt ----
    task = (f"Fix the following GitHub issue in this repository ({inst['repo']}):\n\n"
            f"{ISSUE}\n\nThe fix should be minimal and targeted.")
    report = agent_loop(WORKER, WORKER_SYSTEM, task, 20, "worker")
    diff = subprocess.run(["git", "diff"], cwd=WORKSPACE,
                          capture_output=True, text=True).stdout
    print(f"\n  -- worker done: diff {len(diff)} chars --")

    # ---- Stage 2: cloud review ----
    review_task = (
        f"GitHub issue in {inst['repo']}:\n\n{ISSUE}\n\n"
        f"=== LOCAL MODEL'S DIFF ===\n{diff[:20000]}\n\n"
        f"=== LOCAL MODEL'S REPORT ===\n{report[:3000]}\n\n"
        "Review this fix. Accept it or repair it.")
    verdict = agent_loop(ORCHESTRATOR, REVIEWER_SYSTEM, review_task, 12,
                         "reviewer", {"output_config": {"effort": "medium"}})
    print(f"\n  [verdict] {verdict.strip()[:400]}")

    final_diff = subprocess.run(["git", "diff"], cwd=WORKSPACE,
                                capture_output=True, text=True).stdout
    rec = {"instance_id": iid, "arm": "localfirst", "meter": meter.summary(),
           "verdict": verdict.strip()[:500], "diff_chars": len(final_diff)}
    with open(os.path.join(HERE, f"patch_{iid}_localfirst.diff"), "w") as f:
        f.write(final_diff)
    with open(os.path.join(HERE, f"result_{iid}_localfirst.json"), "w") as f:
        json.dump(rec, f, indent=1)
    print(json.dumps(rec["meter"], indent=1))


if __name__ == "__main__":
    main()

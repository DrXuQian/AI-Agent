#!/usr/bin/env python3
"""
Escalation architecture for SWE-bench: the free local worker attempts the fix
and SELF-ASSESSES. If it claims success, we stop — cloud cost is ZERO. Only
when it gives up does the cloud model take over (with the worker's notes).

  python3 swebench_escalate.py <instance_id>

The whole architecture hinges on self-assessment quality: a false "solved"
ships a broken fix silently. We grade every run officially afterwards, so the
gate's false-positive rate is measured, not assumed.

Env: WORKER_MODEL (default claude-sonnet-4-6), ARM_TAG (suffix for filenames).
"""

import json
import os
import subprocess
import sys

import anthropic

ORCHESTRATOR = "claude-fable-5"
WORKER = os.environ.get("WORKER_MODEL", "claude-sonnet-4-6")
HERE = os.path.dirname(os.path.abspath(__file__))

PRICE = {
    "claude-fable-5": (10.0, 50.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
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
    "(temporary repro scripts in the repo root are fine; delete them when done).\n\n"
    "SELF-ASSESSMENT IS CRITICAL. Your FINAL message must start with exactly one "
    "of:\n"
    "  VERDICT: solved   — only if you applied a fix AND verified it with "
    "passing tests / reproduction evidence in this session.\n"
    "  VERDICT: unsolved — if you are not confident, could not verify, ran out "
    "of leads, or the fix feels uncertain. Choosing 'unsolved' escalates to a "
    "stronger model and is the RIGHT call when unsure — a false 'solved' ships "
    "a broken fix.\n"
    "Then: root cause, change made, verification evidence (max 10 lines)."
)

CLOUD_SYSTEM = (
    "You are the senior cloud engineer. A local model attempted this bug fix "
    "and GAVE UP; its notes and current repo diff are in the user message. The "
    "workspace still contains its partial changes — keep what helps, or revert "
    "with 'git checkout -- <path>' / 'git checkout -- .' and start clean.\n"
    "- Localize, fix, and verify with run_command "
    "('.venv/bin/python -m pytest <file> -q --tb=short').\n"
    "- NEVER modify files under tests/ or testing/.\n"
    "- No prose between tool calls. Final message: at most 8 short lines."
)


def reset_repo(repo_dir, base_commit):
    subprocess.run(["git", "checkout", "-qf", base_commit], cwd=repo_dir, check=True)
    subprocess.run(["git", "clean", "-qfd", "-e", ".venv"], cwd=repo_dir, check=True)


def main():
    global WORKSPACE
    iid = sys.argv[1]
    tag = os.environ.get("ARM_TAG", "")
    inst = next(r for r in json.load(open(os.path.join(HERE, "candidates.json")))
                if r["instance_id"] == iid)
    WORKSPACE = os.path.join(HERE, "repos", iid)
    reset_repo(WORKSPACE, inst["base_commit"])

    print(f"### {iid} [escalate{tag}] worker={WORKER} ###")
    task = (f"Fix the following GitHub issue in this repository ({inst['repo']}):\n\n"
            f"{inst['problem_statement']}\n\nThe fix should be minimal and targeted.")

    # ---- Stage 1: free local attempt with self-assessment ----
    report = agent_loop(WORKER, WORKER_SYSTEM, task, 20, "worker")
    claimed = "solved" if report.strip().lower().startswith("verdict: solved") else "unsolved"
    print(f"\n  == worker verdict: {claimed} ==")

    escalated = False
    if claimed != "solved":
        # ---- Stage 2: cloud takes over ----
        escalated = True
        diff = subprocess.run(["git", "diff"], cwd=WORKSPACE,
                              capture_output=True, text=True).stdout
        cloud_task = (
            f"GitHub issue in {inst['repo']}:\n\n{inst['problem_statement']}\n\n"
            f"=== LOCAL MODEL'S NOTES (it gave up) ===\n{report[:3000]}\n\n"
            f"=== CURRENT REPO DIFF (its partial attempt) ===\n{diff[:15000]}\n\n"
            "Take over and fix the issue.")
        final = agent_loop(ORCHESTRATOR, CLOUD_SYSTEM, cloud_task, 25, "cloud",
                           {"output_config": {"effort": "medium"}})
        print(f"\n  [cloud final] {final.strip()[:300]}")

    final_diff = subprocess.run(["git", "diff"], cwd=WORKSPACE,
                                capture_output=True, text=True).stdout
    rec = {"instance_id": iid, "arm": "escalate" + tag, "worker_model": WORKER,
           "claimed": claimed, "escalated": escalated,
           "meter": meter.summary(), "diff_chars": len(final_diff)}
    with open(os.path.join(HERE, f"patch_{iid}_escalate{tag}.diff"), "w") as f:
        f.write(final_diff)
    with open(os.path.join(HERE, f"result_{iid}_escalate{tag}.json"), "w") as f:
        json.dump(rec, f, indent=1)
    print(json.dumps({k: rec[k] for k in ("claimed", "escalated")},),
          "| cloud_cost:", rec["meter"]["cloud_cost"])


if __name__ == "__main__":
    main()

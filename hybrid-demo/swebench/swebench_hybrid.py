#!/usr/bin/env python3
"""
SWE-bench Lite hybrid runner.

Arms:
  python3 swebench_hybrid.py <instance_id>                 # hybrid (Fable 5 + Sonnet worker)
  python3 swebench_hybrid.py <instance_id> --no-delegate   # baseline (Fable 5 alone)

Adapted from hybrid_demo_v4 (the savings-optimal config: prompt caching,
effort=medium, out-of-band context sharing, terse reports). New for bug-fix
workloads: delegate_to_local takes optional input_files — the harness inlines
their contents into the worker's prompt out-of-band, so the orchestrator can
delegate "read & locate" and "draft the fixed file" without the file bytes
ever entering its own expensive context.
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

    def summary(self):
        out = {}
        for model, s in self.stats.items():
            out[model] = dict(s, cost=round(self.cost(model), 4))
        out["delegations"] = self.delegations
        out["total_cost"] = round(sum(self.cost(m) for m in self.stats), 4)
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
WORKSPACE = None  # set in main
ISSUE = None


def safe_path(rel):
    p = os.path.normpath(os.path.join(WORKSPACE, rel))
    if not p.startswith(WORKSPACE):
        raise ValueError(f"path escapes workspace: {rel}")
    return p


def read_capped(path, cap=30000):
    c = open(path).read()
    return c if len(c) <= cap else c[:cap] + "\n...(truncated)"


def run_worker(task, input_files, output_file):
    meter.delegations += 1
    tag = []
    if input_files:
        tag.append(f"reads {input_files}")
    if output_file:
        tag.append(f"writes {output_file}")
    print(f"\n  >>> delegate #{meter.delegations}  [{'; '.join(tag)}]")
    print(f"      {task.strip().splitlines()[0][:88]}")

    attached = ""
    for f in (input_files or [])[:6]:
        p = safe_path(f)
        attached += (f"\n\n=== FILE: {f} ===\n" + (read_capped(p) if os.path.exists(p)
                     else "(does not exist)"))

    resp = client.messages.create(
        model=WORKER,
        max_tokens=8000,
        system=(
            "You are a focused coding worker on a local device, helping fix a bug "
            "in a real repository. You see the original GitHub issue, your subtask "
            "from the orchestrator, and any attached files. If asked to produce a "
            "file, return ONLY the complete file content — no markdown fences, no "
            "commentary. If asked to analyze/locate, answer concisely.\n\n"
            "=== GITHUB ISSUE ===\n" + ISSUE + attached
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
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        with open(p, "w") as f:
            f.write(text)
        return (f"written to {output_file} ({len(text.splitlines())} lines). "
                "Verify with run_command.")
    return text if len(text) < 8000 else text[:8000] + "\n...(truncated)"


def tool_write_file(path, content):
    p = safe_path(path)
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with open(p, "w") as f:
        f.write(content)
    return f"wrote {path} ({len(content)} chars)"


def tool_read_file(path):
    p = safe_path(path)
    if not os.path.exists(p):
        return f"ERROR: {path} does not exist"
    return read_capped(p, 20000)


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


TOOLS = [
    {
        "name": "delegate_to_local",
        "description": (
            "Hand off a subtask to the cheap on-device local model. It "
            "automatically sees the GitHub issue, plus any input_files you list "
            "(their full contents are attached to it for free — they do NOT enter "
            "your context). Uses: (a) analyze/locate within given files, "
            "(b) produce a complete fixed version of one file per your exact "
            "change spec (set output_file, usually same path). Keep your message "
            "short: state the decided change precisely; don't restate the issue. "
            "You own the diagnosis and the decision of WHAT to change."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {"type": "string"},
                "input_files": {"type": "array", "items": {"type": "string"}},
                "output_file": {"type": "string"},
            },
            "required": ["task"],
        },
    },
    {
        "name": "write_file",
        "description": "Write a workspace file yourself (small or surgical edits).",
        "input_schema": {"type": "object",
                         "properties": {"path": {"type": "string"},
                                        "content": {"type": "string"}},
                         "required": ["path", "content"]},
    },
    {
        "name": "read_file",
        "description": "Read a workspace file into YOUR context. Expensive — prefer grep via run_command, or delegate analysis.",
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}},
                         "required": ["path"]},
    },
    {
        "name": "run_command",
        "description": ("Run a shell command in the repo root. Use '.venv/bin/python -m pytest' "
                        "for tests; grep/sed for cheap exploration."),
        "input_schema": {"type": "object", "properties": {"command": {"type": "string"}},
                         "required": ["command"]},
    },
]

SYSTEM_HYBRID = (
    "You are the orchestrator of a hybrid bug-fixing setup: a powerful but "
    "expensive cloud model paired with a cheap on-device local model "
    "(delegate_to_local). You work in a real repository checkout with "
    "write_file / read_file / run_command (the project is installed in .venv).\n\n"
    "Cost discipline (your tokens are 10x the worker's):\n"
    "- Localize the bug cheaply: grep via run_command; delegate file-level "
    "analysis with input_files instead of reading big files yourself.\n"
    "- YOU decide the fix. Then either apply a small surgical edit yourself "
    "(write_file after a minimal read) or delegate the full-file rewrite with "
    "an exact change spec (input_files=[file], output_file=file).\n"
    "- Verify by running the relevant tests with run_command "
    "('.venv/bin/python -m pytest <test file> -q --tb=short'). Also add/run a "
    "quick reproduction if the issue includes one.\n"
    "- NEVER modify files under tests/ or testing/ — graders use official tests.\n"
    "- No prose between tool calls. Final message: at most 8 short lines "
    "(root cause, change made, verification result)."
)

SYSTEM_BASELINE = (
    "You are a bug-fixing agent working in a real repository checkout with "
    "write_file / read_file / run_command (the project is installed in .venv).\n"
    "- Localize the bug (grep/read), decide the fix, apply it.\n"
    "- Verify with run_command ('.venv/bin/python -m pytest <file> -q --tb=short').\n"
    "- NEVER modify files under tests/ or testing/ — graders use official tests.\n"
    "- No prose between tool calls. Final message: at most 8 short lines "
    "(root cause, change made, verification result)."
)


def run_orchestrator(task, system, tools):
    system_blocks = [{"type": "text", "text": system,
                      "cache_control": {"type": "ephemeral"}}]
    messages = [{"role": "user", "content": [{"type": "text", "text": task}]}]

    for turn in range(1, 31):
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
            output_config={"effort": "medium"},
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

        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for b in resp.content:
            if b.type != "tool_use":
                continue
            try:
                if b.name == "delegate_to_local":
                    out = run_worker(b.input["task"], b.input.get("input_files"),
                                     b.input.get("output_file"))
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


def reset_repo(repo_dir, base_commit):
    subprocess.run(["git", "checkout", "-qf", base_commit], cwd=repo_dir, check=True)
    subprocess.run(["git", "clean", "-qfd", "-e", ".venv"], cwd=repo_dir, check=True)


def main():
    global WORKSPACE, ISSUE
    iid = sys.argv[1]
    baseline = "--no-delegate" in sys.argv
    inst = next(r for r in json.load(open(os.path.join(HERE, "instances.json")))
                if r["instance_id"] == iid)
    WORKSPACE = os.path.join(HERE, "repos", iid)
    ISSUE = inst["problem_statement"]
    reset_repo(WORKSPACE, inst["base_commit"])

    arm = "baseline" if baseline else "hybrid"
    tools = [t for t in TOOLS if t["name"] != "delegate_to_local"] if baseline else TOOLS
    system = SYSTEM_BASELINE if baseline else SYSTEM_HYBRID

    task = (f"Fix the following GitHub issue in this repository "
            f"({inst['repo']}, checked out at the buggy commit):\n\n"
            f"{ISSUE}\n\n"
            "The fix should be minimal and targeted. Do not modify test files.")

    print(f"### {iid} [{arm}] ###")
    final = run_orchestrator(task, system, tools)
    print(f"\n  [final] {final.strip()[:600]}")

    # Save the diff the agent produced.
    diff = subprocess.run(["git", "diff"], cwd=WORKSPACE,
                          capture_output=True, text=True).stdout
    rec = {"instance_id": iid, "arm": arm, "meter": meter.summary(),
           "diff_chars": len(diff)}
    with open(os.path.join(HERE, f"patch_{iid}_{arm}.diff"), "w") as f:
        f.write(diff)
    with open(os.path.join(HERE, f"result_{iid}_{arm}.json"), "w") as f:
        json.dump(rec, f, indent=1)
    print(json.dumps(rec["meter"], indent=1))


if __name__ == "__main__":
    main()

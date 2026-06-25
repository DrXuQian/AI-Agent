#!/usr/bin/env python3
"""
Local-as-Context-Engine: edge+cloud collaboration that attacks the INPUT-token
half of cloud cost (which baseline burns on exploration/file-reading).

Stage 1 (FREE local): a local agent explores the repo (read/grep/run) and emits
  a COMPACT context package: root-cause hypothesis, suspect file + line ranges,
  the minimal relevant code excerpts (verbatim), and a repro/test command.
Stage 2 (CLOUD = Opus 4.8): receives ONLY issue + package. It decides and writes
  the fix and verifies with tests. It does NOT explore the repo. When it needs
  more code it calls request_local_context(query) — a FRESH free local retrieval
  — instead of reading whole files into its expensive context.

Cloud stays the reasoner (quality preserved); cloud input collapses (no
multi-turn whole-file exploration). Env: WORKER_MODEL, ARM_TAG.
"""

import json
import os
import subprocess
import sys

import anthropic

CLOUD = "claude-opus-4-8"
WORKER = os.environ.get("WORKER_MODEL", "claude-sonnet-4-6")
HERE = os.path.dirname(os.path.abspath(__file__))

PRICE = {
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


class Meter:
    def __init__(self):
        self.stats = {}

    def add(self, model, usage):
        s = self.stats.setdefault(model, {"in": 0, "cw": 0, "cr": 0, "out": 0, "calls": 0})
        s["in"] += usage.input_tokens
        s["cw"] += getattr(usage, "cache_creation_input_tokens", 0) or 0
        s["cr"] += getattr(usage, "cache_read_input_tokens", 0) or 0
        s["out"] += usage.output_tokens
        s["calls"] += 1

    def cost(self, model):
        pin, pout = PRICE[model]
        s = self.stats[model]
        return (s["in"] * pin + s["cw"] * 1.25 * pin + s["cr"] * 0.1 * pin + s["out"] * pout) / 1e6

    def summary(self):
        out = {m: dict(s, cost=round(self.cost(m), 4)) for m, s in self.stats.items()}
        out["cloud_cost"] = round(self.cost(CLOUD), 4) if CLOUD in self.stats else 0.0
        return out


meter = Meter()


def make_client():
    tf = os.environ.get("CLAUDE_SESSION_INGRESS_TOKEN_FILE")
    if tf and os.path.exists(tf):
        return anthropic.Anthropic(auth_token=open(tf).read().strip(),
                                   default_headers={"anthropic-beta": "oauth-2025-04-20"})
    return anthropic.Anthropic()


client = make_client()
WORKSPACE = None
ISSUE = None


def safe_path(rel):
    p = os.path.normpath(os.path.join(WORKSPACE, rel))
    if not p.startswith(WORKSPACE):
        raise ValueError("escape")
    return p


def t_write(path, content):
    p = safe_path(path); os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    open(p, "w").write(content); return f"wrote {path} ({len(content)} chars)"


def t_read(path, cap=18000):
    p = safe_path(path)
    if not os.path.exists(p): return f"ERROR: {path} missing"
    c = open(p).read(); return c if len(c) <= cap else c[:cap] + "\n...(truncated)"


def t_run(command, cap=4000):
    print(f"      $ {command[:90]}")
    try:
        r = subprocess.run(command, shell=True, cwd=WORKSPACE, capture_output=True,
                           text=True, timeout=300)
        o = (r.stdout + r.stderr).strip()
        if len(o) > cap: o = o[:cap//2] + "\n...(truncated)...\n" + o[-cap//2:]
        return f"exit {r.returncode}\n{o}"
    except subprocess.TimeoutExpired:
        return "ERROR: timeout"


EXPLORE_TOOLS = [
    {"name": "read_file", "description": "Read a file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "run_command", "description": "Run a shell command (grep/ls/sed/pytest) in repo root.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
]


def local_agent(task, system, max_turns=14, final_nudge=None):
    """A free local agent loop with read/grep tools. Returns its final text.
    If it exhausts turns, make one FORCED no-tools call so it always emits a
    real package/answer instead of dying at the turn limit."""
    sysb = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
    msgs = [{"role": "user", "content": [{"type": "text", "text": task}]}]
    for _ in range(max_turns):
        last = msgs[-1]["content"]
        if isinstance(last, list) and last and isinstance(last[-1], dict):
            for m in msgs:
                for blk in (m["content"] if isinstance(m["content"], list) else []):
                    if isinstance(blk, dict): blk.pop("cache_control", None)
            last[-1]["cache_control"] = {"type": "ephemeral"}
        resp = client.messages.create(model=WORKER, max_tokens=6000, system=sysb,
                                       tools=EXPLORE_TOOLS, messages=msgs)
        meter.add(WORKER, resp.usage)
        if resp.stop_reason != "tool_use":
            return "".join(b.text for b in resp.content if b.type == "text")
        msgs.append({"role": "assistant", "content": resp.content})
        res = []
        for b in resp.content:
            if b.type != "tool_use": continue
            try:
                out = t_read(b.input["path"]) if b.name == "read_file" else t_run(b.input["command"])
            except Exception as e:
                out = f"ERROR: {e}"
            res.append({"type": "tool_result", "tool_use_id": b.id, "content": out})
        msgs.append({"role": "user", "content": res})
    # Out of turns: force a final summary with NO tools so we always get output.
    msgs.append({"role": "user", "content":
                 (final_nudge or "Stop exploring now. Output your final answer "
                  "from what you've already found.")})
    resp = client.messages.create(model=WORKER, max_tokens=6000, system=sysb,
                                   messages=msgs)
    meter.add(WORKER, resp.usage)
    return "".join(b.text for b in resp.content if b.type == "text") or "(no package)"


EXPLORER_SYS = (
    "You are a free local code-exploration assistant. A powerful but EXPENSIVE "
    "cloud model will fix the bug; your job is to do all the cheap exploration "
    "for it and hand back a COMPACT, high-signal context package so it never has "
    "to read the repo itself.\n"
    "Explore with read_file / run_command (grep, ls, sed, pytest). Then output a "
    "package with EXACTLY these sections:\n"
    "## ROOT CAUSE\n<2-4 sentences: the precise mechanism of the bug>\n"
    "## FIX LOCATION\n<file path(s) + function/line ranges to change>\n"
    "## RELEVANT CODE\n<verbatim minimal excerpts of ONLY the lines that matter, "
    "with file:line headers — enough that the fixer needs nothing else>\n"
    "## REPRO / TEST\n<the exact command to reproduce or the test file to run>\n"
    "## NOTES\n<API conventions, similar patterns elsewhere, gotchas the fixer "
    "must respect>\n"
    "Be precise and SHORT — include the lines that matter, omit everything else. "
    "Do NOT propose the full fix; the cloud decides that."
)

RETRIEVER_SYS = (
    "You are a free local retrieval assistant with read_file / run_command on a "
    "repo. Answer the cloud model's specific question with the exact code "
    "excerpts or command output it needs. Be precise and compact: paste only the "
    "relevant lines (with file:line), nothing else."
)

FIXER_SYS = (
    "You are the expensive cloud engineer (Opus 4.8). A FREE local assistant has "
    "already explored the repo and given you a compact context package. Your "
    "tokens cost the most — so do NOT read repo files yourself. Decide and apply "
    "the fix from the package; if you need more code, call request_local_context "
    "(a free local retrieval) rather than read_file. Apply edits with write_file, "
    "verify with run_command ('.venv/bin/python -m pytest <file> -q --tb=line'). "
    "NEVER modify files under tests/ or testing/. No prose between tool calls. "
    "Final message: at most 6 short lines (root cause, change, verification)."
)

FIXER_TOOLS = [
    {"name": "request_local_context",
     "description": ("Ask the FREE local assistant for more code/context (it has "
                     "the repo). Use this instead of reading files yourself. "
                     "Returns compact excerpts."),
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "write_file", "description": "Apply an edit.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "run_command", "description": "Run a command (tests) in repo root.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "LAST RESORT: read a file into your expensive context. Prefer request_local_context.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
]


def reset_repo(repo, commit):
    subprocess.run(["git", "checkout", "-qf", commit], cwd=repo, check=True)
    subprocess.run(["git", "clean", "-qfd", "-e", ".venv"], cwd=repo, check=True)


def main():
    global WORKSPACE, ISSUE
    iid = sys.argv[1]; tag = os.environ.get("ARM_TAG", "")
    inst = next(r for r in json.load(open(f"{HERE}/candidates.json")) if r["instance_id"] == iid)
    WORKSPACE = f"{HERE}/repos/{iid}"; ISSUE = inst["problem_statement"]
    reset_repo(WORKSPACE, inst["base_commit"])
    print(f"### {iid} [context-engine{tag}] worker={WORKER} cloud={CLOUD} ###")

    # Stage 1: free local exploration -> compact package
    pkg = local_agent(
        f"Bug to investigate in {inst['repo']}:\n\n{ISSUE}\n\nProduce the context package.",
        EXPLORER_SYS,
        final_nudge=("Stop exploring. Output the full context package now "
                     "(ROOT CAUSE / FIX LOCATION / RELEVANT CODE / REPRO / NOTES) "
                     "from what you have already found."))
    print(f"\n  -- context package: {len(pkg)} chars --")

    # Stage 2: cloud fixes using the package; request_local_context is free
    sysb = [{"type": "text", "text": FIXER_SYS, "cache_control": {"type": "ephemeral"}}]
    task = (f"GitHub issue in {inst['repo']}:\n\n{ISSUE}\n\n"
            f"=== CONTEXT PACKAGE (from free local assistant) ===\n{pkg}\n\n"
            "Apply and verify the fix.")
    msgs = [{"role": "user", "content": [{"type": "text", "text": task}]}]
    final = "(no final)"
    for _ in range(20):
        last = msgs[-1]["content"]
        if isinstance(last, list) and last and isinstance(last[-1], dict):
            for m in msgs:
                for blk in (m["content"] if isinstance(m["content"], list) else []):
                    if isinstance(blk, dict): blk.pop("cache_control", None)
            last[-1]["cache_control"] = {"type": "ephemeral"}
        resp = client.messages.create(model=CLOUD, max_tokens=8000,
                                       output_config={"effort": "medium"},
                                       system=sysb, tools=FIXER_TOOLS, messages=msgs)
        meter.add(CLOUD, resp.usage)
        for b in resp.content:
            if b.type == "text" and b.text.strip():
                print(f"\n  [cloud] {b.text.strip()[:300]}")
        if resp.stop_reason != "tool_use":
            final = "".join(b.text for b in resp.content if b.type == "text"); break
        msgs.append({"role": "assistant", "content": resp.content})
        res = []
        for b in resp.content:
            if b.type != "tool_use": continue
            try:
                if b.name == "request_local_context":
                    print(f"      -> local retrieval: {b.input['query'][:70]}")
                    out = local_agent(b.input["query"], RETRIEVER_SYS, max_turns=8)
                elif b.name == "write_file":
                    out = t_write(b.input["path"], b.input["content"])
                elif b.name == "run_command":
                    out = t_run(b.input["command"])
                elif b.name == "read_file":
                    out = t_read(b.input["path"])
                else:
                    out = "unknown"
            except Exception as e:
                out = f"ERROR: {e}"
            res.append({"type": "tool_result", "tool_use_id": b.id, "content": out})
        msgs.append({"role": "user", "content": res})

    diff = subprocess.run(["git", "diff"], cwd=WORKSPACE, capture_output=True, text=True).stdout
    rec = {"instance_id": iid, "arm": "ctxengine" + tag, "worker_model": WORKER,
           "meter": meter.summary(), "package_chars": len(pkg), "diff_chars": len(diff)}
    open(f"{HERE}/patch_{iid}_ctxengine{tag}.diff", "w").write(diff)
    json.dump(rec, open(f"{HERE}/result_{iid}_ctxengine{tag}.json", "w"), indent=1)
    print("cloud_cost:", rec["meter"]["cloud_cost"], "| pkg:", len(pkg), "chars")


if __name__ == "__main__":
    main()

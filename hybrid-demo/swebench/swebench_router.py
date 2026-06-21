#!/usr/bin/env python3
"""
Free local triage router. Reads the issue + does a couple of cheap greps on the
repo (all free, local model), then classifies the task:
  SURGICAL    -> a localized fix; pure cloud explores faster than reading a package
  EXPLORATORY -> spans files / needs digging; route to context-engine

Emits ROUTE for each instance. We then synthesize the routed cost by picking,
per instance, the already-measured baseline_opus (SURGICAL) or ctxengine
(EXPLORATORY) result — so the router's only added cost is this free triage.

Usage: python3 swebench_router.py <instance_id>
"""
import json, os, subprocess, sys
import anthropic

WORKER = os.environ.get("WORKER_MODEL", "claude-sonnet-4-6")
HERE = os.path.dirname(os.path.abspath(__file__))
PRICE = {"claude-sonnet-4-6": (3.0, 15.0), "claude-haiku-4-5": (1.0, 5.0)}

triage_cost = [0.0]


def make_client():
    tf = os.environ.get("CLAUDE_SESSION_INGRESS_TOKEN_FILE")
    if tf and os.path.exists(tf):
        return anthropic.Anthropic(auth_token=open(tf).read().strip(),
                                   default_headers={"anthropic-beta": "oauth-2025-04-20"})
    return anthropic.Anthropic()


client = make_client()
WORKSPACE = None


def t_run(command, cap=2500):
    try:
        r = subprocess.run(command, shell=True, cwd=WORKSPACE, capture_output=True,
                           text=True, timeout=60)
        o = (r.stdout + r.stderr).strip()
        return f"exit {r.returncode}\n{o[:cap]}"
    except subprocess.TimeoutExpired:
        return "timeout"


TRIAGE_TOOLS = [{"name": "grep", "description": "Run grep/ls/find in the repo to gauge how localized the bug is.",
                 "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}]

TRIAGE_SYS = (
    "You are a free local triage classifier. Given a bug report, decide how a "
    "fix agent should be routed, to minimize expensive cloud tokens:\n"
    "- SURGICAL: the bug is localized (one file / a few lines, clear symbol). A "
    "cloud model can grep+read the 1-2 relevant spots itself faster than reading "
    "a prepared context package.\n"
    "- EXPLORATORY: the fix needs cross-file digging, unclear location, or "
    "understanding broad code flow. Worth having a free local assistant explore "
    "and hand the cloud a compact package.\n"
    "Use the grep tool 1-3 times to gauge how widely the key symbols spread "
    "across files. Then answer with EXACTLY one line: 'ROUTE: SURGICAL' or "
    "'ROUTE: EXPLORATORY', then one short sentence why."
)


def triage(issue):
    sysb = [{"type": "text", "text": TRIAGE_SYS, "cache_control": {"type": "ephemeral"}}]
    msgs = [{"role": "user", "content": [{"type": "text", "text":
             f"Bug report:\n\n{issue}\n\nClassify the routing."}]}]
    for _ in range(5):
        resp = client.messages.create(model=WORKER, max_tokens=1500, system=sysb,
                                       tools=TRIAGE_TOOLS, messages=msgs)
        pin, pout = PRICE[WORKER]
        triage_cost[0] += (resp.usage.input_tokens * pin + resp.usage.output_tokens * pout) / 1e6
        if resp.stop_reason != "tool_use":
            txt = "".join(b.text for b in resp.content if b.type == "text")
            return ("EXPLORATORY" if "EXPLORATORY" in txt.upper() else "SURGICAL"), txt.strip()[:160]
        msgs.append({"role": "assistant", "content": resp.content})
        res = [{"type": "tool_result", "tool_use_id": b.id, "content": t_run(b.input["command"])}
               for b in resp.content if b.type == "tool_use"]
        msgs.append({"role": "user", "content": res})
    return "EXPLORATORY", "(triage hit turn limit -> default exploratory)"


def main():
    global WORKSPACE
    iid = sys.argv[1]
    inst = next(r for r in json.load(open(f"{HERE}/candidates.json")) if r["instance_id"] == iid)
    WORKSPACE = f"{HERE}/repos/{iid}"
    subprocess.run(["git", "checkout", "-qf", inst["base_commit"]], cwd=WORKSPACE)
    subprocess.run(["git", "clean", "-qfd", "-e", ".venv"], cwd=WORKSPACE)
    route, why = triage(inst["problem_statement"])
    rec = {"instance_id": iid, "route": route, "why": why,
           "triage_cost": round(triage_cost[0], 5)}
    json.dump(rec, open(f"{HERE}/route_{iid}.json", "w"), indent=1)
    print(f"{iid}: ROUTE={route}  triage_cost=${triage_cost[0]:.5f}  ({why[:80]})")


if __name__ == "__main__":
    main()

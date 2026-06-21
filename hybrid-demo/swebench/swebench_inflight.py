#!/usr/bin/env python3
"""
In-flight router: the cost-predictive signal the text-triage router lacked.

Cloud (Opus 4.8) starts fixing with normal repo tools (read/grep/run) under a
small EXPLORE BUDGET. If it produces a verified fix within the budget, we stop
(= baseline behaviour; cheap on surgical fixes, no package overhead). If it
burns the budget WITHOUT a passing test, we inject a FREE local context package
once and let it finish (= context-engine rescue for flailing/exploratory cases).

So routing is decided by observed cloud behaviour, not by guessing from the
issue text. Env: WORKER_MODEL, ARM_TAG. Budget = EXPLORE_BUDGET turns.
"""
import json, os, subprocess, sys
import anthropic

CLOUD = "claude-opus-4-8"
WORKER = os.environ.get("WORKER_MODEL", "claude-sonnet-4-6")
EXPLORE_BUDGET = int(os.environ.get("EXPLORE_BUDGET", "5"))
HERE = os.path.dirname(os.path.abspath(__file__))
PRICE = {"claude-opus-4-8": (5.0, 25.0), "claude-sonnet-4-6": (3.0, 15.0), "claude-haiku-4-5": (1.0, 5.0)}

meter = {}
def add(model, u):
    s = meter.setdefault(model, {"in":0,"cw":0,"cr":0,"out":0,"calls":0})
    s["in"]+=u.input_tokens; s["cw"]+=getattr(u,"cache_creation_input_tokens",0)or 0
    s["cr"]+=getattr(u,"cache_read_input_tokens",0)or 0; s["out"]+=u.output_tokens; s["calls"]+=1
def cost(model):
    pin,pout=PRICE[model]; s=meter[model]
    return (s["in"]*pin+s["cw"]*1.25*pin+s["cr"]*0.1*pin+s["out"]*pout)/1e6

def make_client():
    tf=os.environ.get("CLAUDE_SESSION_INGRESS_TOKEN_FILE")
    if tf and os.path.exists(tf):
        return anthropic.Anthropic(auth_token=open(tf).read().strip(),
                                   default_headers={"anthropic-beta":"oauth-2025-04-20"})
    return anthropic.Anthropic()
client=make_client(); WORKSPACE=None

def safe(rel):
    p=os.path.normpath(os.path.join(WORKSPACE,rel))
    if not p.startswith(WORKSPACE): raise ValueError("escape")
    return p
def t_write(path,content):
    p=safe(path); os.makedirs(os.path.dirname(p)or".",exist_ok=True); open(p,"w").write(content)
    return f"wrote {path} ({len(content)} chars)"
def t_read(path,cap=18000):
    p=safe(path)
    if not os.path.exists(p): return f"ERROR: {path} missing"
    c=open(p).read(); return c if len(c)<=cap else c[:cap]+"\n...(truncated)"
passed=[False]
def t_run(command,cap=4000):
    print(f"      $ {command[:90]}")
    try:
        r=subprocess.run(command,shell=True,cwd=WORKSPACE,capture_output=True,text=True,timeout=300)
        o=(r.stdout+r.stderr).strip()
        # crude success signal: a pytest run that passed
        if "pytest" in command and r.returncode==0 and ("passed" in o or "PASSED" in o):
            passed[0]=True
        if len(o)>cap: o=o[:cap//2]+"\n...(truncated)...\n"+o[-cap//2:]
        return f"exit {r.returncode}\n{o}"
    except subprocess.TimeoutExpired:
        return "ERROR: timeout"

TOOLS=[
 {"name":"read_file","description":"Read a file.","input_schema":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}},
 {"name":"run_command","description":"Run a shell command (grep/ls/sed/pytest) in repo root.","input_schema":{"type":"object","properties":{"command":{"type":"string"}},"required":["command"]}},
 {"name":"write_file","description":"Apply an edit.","input_schema":{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},"required":["path","content"]}},
]
EXPLORE_TOOLS=[t for t in TOOLS if t["name"] in ("read_file","run_command")]

CLOUD_SYS=("You are a senior engineer fixing a bug in a repo (installed in .venv). "
 "Localize, fix, and verify with '.venv/bin/python -m pytest <file> -q --tb=line'. "
 "NEVER modify files under tests/ or testing/. No prose between tool calls. "
 "Final message: <=6 short lines.")

EXPLORER_SYS=("You are a free local code-exploration assistant. Output a COMPACT context "
 "package: ## ROOT CAUSE ## FIX LOCATION ## RELEVANT CODE (verbatim minimal excerpts "
 "with file:line) ## REPRO/TEST ## NOTES. Be precise and short. Don't propose the full fix.")

def local_package(issue):
    sysb=[{"type":"text","text":EXPLORER_SYS,"cache_control":{"type":"ephemeral"}}]
    msgs=[{"role":"user","content":[{"type":"text","text":f"Bug in repo:\n\n{issue}\n\nProduce the package."}]}]
    for _ in range(12):
        resp=client.messages.create(model=WORKER,max_tokens=6000,system=sysb,tools=EXPLORE_TOOLS,messages=msgs)
        add(WORKER,resp.usage)
        if resp.stop_reason!="tool_use":
            return "".join(b.text for b in resp.content if b.type=="text")
        msgs.append({"role":"assistant","content":resp.content})
        res=[]
        for b in resp.content:
            if b.type!="tool_use": continue
            out=t_read(b.input["path"]) if b.name=="read_file" else t_run(b.input["command"])
            res.append({"type":"tool_result","tool_use_id":b.id,"content":out})
        msgs.append({"role":"user","content":res})
    msgs.append({"role":"user","content":"Stop exploring. Output the package now from what you found."})
    resp=client.messages.create(model=WORKER,max_tokens=6000,system=sysb,messages=msgs); add(WORKER,resp.usage)
    return "".join(b.text for b in resp.content if b.type=="text") or "(no package)"

def reset(repo,commit):
    subprocess.run(["git","checkout","-qf",commit],cwd=repo,check=True)
    subprocess.run(["git","clean","-qfd","-e",".venv"],cwd=repo,check=True)

def main():
    global WORKSPACE
    iid=sys.argv[1]; tag=os.environ.get("ARM_TAG","")
    inst=next(r for r in json.load(open(f"{HERE}/candidates.json")) if r["instance_id"]==iid)
    WORKSPACE=f"{HERE}/repos/{iid}"; reset(WORKSPACE,inst["base_commit"])
    issue=inst["problem_statement"]
    print(f"### {iid} [inflight budget={EXPLORE_BUDGET}] cloud={CLOUD} ###")
    sysb=[{"type":"text","text":CLOUD_SYS,"cache_control":{"type":"ephemeral"}}]
    msgs=[{"role":"user","content":[{"type":"text","text":
        f"Fix this GitHub issue in {inst['repo']}:\n\n{issue}\n\nMinimal, targeted."}]}]
    injected=False; rescued=False
    for turn in range(1,25):
        # in-flight trigger: budget burned, no passing test yet -> inject free local package once
        if turn>EXPLORE_BUDGET and not passed[0] and not injected:
            injected=rescued=True
            pkg=local_package(issue)
            print(f"\n  >> budget hit, no pass yet -> inject local package ({len(pkg)} chars)")
            msgs.append({"role":"user","content":[{"type":"text","text":
                "You've spent your exploration budget. A free local assistant prepared "
                "this context package — use it to finish the fix directly:\n\n"+pkg}]})
        last=msgs[-1]["content"]
        if isinstance(last,list) and last and isinstance(last[-1],dict):
            for m in msgs:
                for blk in (m["content"] if isinstance(m["content"],list) else []):
                    if isinstance(blk,dict): blk.pop("cache_control",None)
            last[-1]["cache_control"]={"type":"ephemeral"}
        resp=client.messages.create(model=CLOUD,max_tokens=8000,output_config={"effort":"medium"},
                                    system=sysb,tools=TOOLS,messages=msgs)
        add(CLOUD,resp.usage)
        for b in resp.content:
            if b.type=="text" and b.text.strip(): print(f"\n  [cloud t{turn}] {b.text.strip()[:200]}")
        if resp.stop_reason!="tool_use": break
        msgs.append({"role":"assistant","content":resp.content})
        res=[]
        for b in resp.content:
            if b.type!="tool_use": continue
            try:
                out=t_write(b.input["path"],b.input["content"]) if b.name=="write_file" else \
                    (t_read(b.input["path"]) if b.name=="read_file" else t_run(b.input["command"]))
            except Exception as e: out=f"ERROR: {e}"
            res.append({"type":"tool_result","tool_use_id":b.id,"content":out})
        msgs.append({"role":"user","content":res})
    cc=round(cost(CLOUD),4) if CLOUD in meter else 0.0
    rec={"instance_id":iid,"arm":"inflight"+tag,"rescued":rescued,
         "cloud_cost":cc,"meter":{m:dict(s,cost=round(cost(m),4)) for m,s in meter.items()}}
    json.dump(rec,open(f"{HERE}/result_{iid}_inflight{tag}.json","w"),indent=1)
    print(f"rescued={rescued} cloud_cost=${cc}")

if __name__=="__main__":
    main()

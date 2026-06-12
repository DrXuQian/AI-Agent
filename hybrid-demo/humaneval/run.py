#!/usr/bin/env python3
"""
HumanEval+ four-arm runner. Cloud = Opus 4.8; worker = Sonnet 4.6 (or WORKER_MODEL).
Cost accounting is CLOUD-ONLY (local worker assumed free).

Arms (env ARM):
  baseline   : cloud solves alone (one shot, no tools).
  escalate   : worker writes solution + its OWN tests, self-assesses solved/unsolved;
               escalate to cloud ONLY if unsolved. Cloud cost = 0 when worker solves.
  localfirst : worker solves; cloud reviews/fixes every task.

Grading is always the hidden EvalPlus suite (worker never sees it).
Usage: python3 run.py <task_id>    (ARM, WORKER_MODEL via env)
"""
import json, os, re, subprocess, sys, tempfile
import anthropic

CLOUD = "claude-opus-4-8"
WORKER = os.environ.get("WORKER_MODEL", "claude-sonnet-4-6")
ARM = os.environ.get("ARM", "baseline")
HERE = os.path.dirname(os.path.abspath(__file__))

PRICE = {
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}

class Meter:
    def __init__(self): self.s = {}
    def add(self, model, u):
        d = self.s.setdefault(model, {"in":0,"cw":0,"cr":0,"out":0,"calls":0})
        d["in"]+=u.input_tokens; d["cw"]+=getattr(u,"cache_creation_input_tokens",0) or 0
        d["cr"]+=getattr(u,"cache_read_input_tokens",0) or 0; d["out"]+=u.output_tokens; d["calls"]+=1
    def cost(self, model):
        pin,pout=PRICE[model]; d=self.s[model]
        return (d["in"]*pin + d["cw"]*1.25*pin + d["cr"]*0.1*pin + d["out"]*pout)/1e6
    def cloud_cost(self): return round(self.cost(CLOUD),4) if CLOUD in self.s else 0.0
    def summary(self):
        return {m: dict(d, cost=round(self.cost(m),4)) for m,d in self.s.items()} | {"cloud_cost": self.cloud_cost()}

meter = Meter()

def client():
    tf = os.environ.get("CLAUDE_SESSION_INGRESS_TOKEN_FILE")
    if tf and os.path.exists(tf):
        return anthropic.Anthropic(auth_token=open(tf).read().strip(),
                                   default_headers={"anthropic-beta":"oauth-2025-04-20"})
    return anthropic.Anthropic()
C = client()

def extract_code(text):
    m = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.S)
    return (m.group(1) if m else text).strip() + "\n"

def one_shot(model, system, user, extra=None):
    r = C.messages.create(model=model, max_tokens=4000, system=system,
                          messages=[{"role":"user","content":user}], **(extra or {}))
    meter.add(model, r.usage)
    return "".join(b.text for b in r.content if b.type=="text")

# --- local sandbox to run worker's own tests (free) ---
def run_py(code, timeout=30):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(code); p=f.name
    try:
        r=subprocess.run([sys.executable,p],capture_output=True,text=True,timeout=timeout)
        return r.returncode, (r.stdout+r.stderr)[-2000:]
    except subprocess.TimeoutExpired:
        return 124,"timeout"
    finally:
        os.unlink(p)

def main():
    tid = sys.argv[1]
    t = next(x for x in json.load(open(f"{HERE}/tasks.json")) if x["task_id"]==tid)
    prompt, entry = t["prompt"], t["entry_point"]
    solution = None
    escalated = False
    claimed = None

    if ARM == "baseline":
        sys_p = ("You are an expert Python programmer. Implement the function. "
                 "Return ONLY a fenced python code block with the complete function "
                 "(including imports and signature). No prose.")
        out = one_shot(CLOUD, sys_p, prompt, {"output_config":{"effort":"medium"}})
        solution = extract_code(out)

    else:
        # Stage 1 (free worker): solve + write+run own tests + self-assess.
        wsys = ("You are a local coding model. Implement the requested function, then "
                "WRITE 3-6 of your own test assertions and mentally run them. Return TWO "
                "fenced python blocks: first the complete solution (imports+signature+body), "
                "second your tests calling the function. After the blocks, output exactly one "
                "line: 'VERDICT: solved' if you are confident all your tests pass, else "
                "'VERDICT: unsolved'.")
        out = one_shot(WORKER, wsys, prompt)
        blocks = re.findall(r"```(?:python)?\s*\n(.*?)```", out, re.S)
        solution = (blocks[0].strip()+"\n") if blocks else extract_code(out)
        worker_tests = blocks[1].strip() if len(blocks)>1 else ""
        m = re.search(r"VERDICT:\s*(solved|unsolved)", out, re.I)
        claimed = m.group(1).lower() if m else "unsolved"

        # Objective local check: actually run the worker's own tests (free).
        if worker_tests:
            rc,_ = run_py(solution+"\n"+worker_tests)
            self_pass = (rc==0)
        else:
            self_pass = False
        # Trust verdict only if its own tests actually pass.
        worker_confident = (claimed=="solved" and self_pass)

        if ARM == "escalate":
            if not worker_confident:
                escalated = True
                csys = ("You are Opus, the senior cloud engineer. A local model attempted "
                        "this and was not confident. Here is the task and its attempt. "
                        "Return ONLY a fenced python block with the correct complete function.")
                u = f"TASK:\n{prompt}\n\nLOCAL ATTEMPT:\n{solution}\n\nLOCAL TESTS:\n{worker_tests}"
                out = one_shot(CLOUD, csys, u, {"output_config":{"effort":"medium"}})
                solution = extract_code(out)
        elif ARM == "localfirst":
            csys = ("You are Opus, reviewing a local model's solution. If correct, return it "
                    "unchanged; if wrong, fix it. Return ONLY a fenced python block with the "
                    "final complete function.")
            u = f"TASK:\n{prompt}\n\nLOCAL SOLUTION:\n{solution}"
            out = one_shot(CLOUD, csys, u, {"output_config":{"effort":"medium"}})
            solution = extract_code(out)

    # write solution & grade
    tag = os.environ.get("ARM_TAG","")
    sol_file = f"{HERE}/sol_{tid.replace('/','_')}_{ARM}{tag}.py"
    open(sol_file,"w").write(solution)
    g = subprocess.run([sys.executable, f"{HERE}/grade.py", tid, sol_file],
                       capture_output=True, text=True)
    resolved = g.returncode==0
    rec = {"task_id":tid, "arm":ARM, "worker":WORKER, "cloud":CLOUD,
           "resolved":resolved, "escalated":escalated, "claimed":claimed,
           "cloud_cost":meter.cloud_cost(), "meter":meter.summary()}
    json.dump(rec, open(f"{HERE}/res_{tid.replace('/','_')}_{ARM}{tag}.json","w"))
    print(f"{tid} [{ARM}] {'PASS' if resolved else 'FAIL'} "
          f"cloud=${meter.cloud_cost():.4f} escalated={escalated} claimed={claimed}")

if __name__ == "__main__":
    main()

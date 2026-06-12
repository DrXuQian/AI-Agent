#!/usr/bin/env python3
"""
Validate a SWE-bench candidate end-to-end in this environment:
  1. clone from local mirror at base_commit, create venv, pip install -e .
  2. pre-fix: F2P must FAIL (and not purely by collection error)
  3. gold check: apply official patch -> F2P must PASS -> revert
  4. record P2P baseline (sampled tests that pass pre-fix); need >= 5
Writes validated flag into validated/<iid>.json. Usage: validate_instance.py <iid>
"""
import json, os, subprocess, sys, random

HERE = os.path.dirname(os.path.abspath(__file__))

def sh(cmd, cwd, **kw):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          timeout=kw.pop("timeout", 900), **kw)

def main():
    iid = sys.argv[1]
    inst = next(r for r in json.load(open(f"{HERE}/candidates.json"))
                if r["instance_id"] == iid)
    repo_dir = f"{HERE}/repos/{iid}"
    mirror = f"{HERE}/mirrors/{inst['repo'].replace('/', '_')}"
    out = {"instance_id": iid, "ok": False, "reason": ""}

    def finish(reason, ok=False):
        out["ok"] = ok; out["reason"] = reason
        os.makedirs(f"{HERE}/validated", exist_ok=True)
        json.dump(out, open(f"{HERE}/validated/{iid}.json", "w"))
        print(f"{iid}: {'OK' if ok else 'SKIP'} ({reason})")
        sys.exit(0)

    # 1. clone + venv + install
    if not os.path.isdir(f"{repo_dir}/.git"):
        r = sh(["git", "clone", "--local", "--quiet", mirror, repo_dir], cwd=HERE)
        if r.returncode != 0:
            finish("clone failed")
    sh(["git", "checkout", "-qf", inst["base_commit"]], cwd=repo_dir)
    sh(["git", "clean", "-qfd", "-e", ".venv"], cwd=repo_dir)
    if not os.path.exists(f"{repo_dir}/.venv"):
        sh([sys.executable, "-m", "venv", ".venv"], cwd=repo_dir)
    r = sh([".venv/bin/pip", "install", "-q", "-e", ".", "pytest"], cwd=repo_dir)
    if r.returncode != 0:
        finish("pip install failed: " + r.stderr.strip()[-200:])
    if inst["repo"] == "pallets/flask":
        sh([".venv/bin/pip", "install", "-q", "werkzeug<3", "jinja2<3.2"], cwd=repo_dir)

    f2p = json.loads(inst["FAIL_TO_PASS"])
    p2p = json.loads(inst["PASS_TO_PASS"])

    def apply_tp():  # test patch
        return sh(["git", "apply", "--whitespace=nowarn", "-"], cwd=repo_dir,
                  input=inst["test_patch"])
    def revert_tp():
        sh(["git", "apply", "-R", "--whitespace=nowarn", "-"], cwd=repo_dir,
           input=inst["test_patch"])
    def run_tests(tests):
        return sh([".venv/bin/python", "-m", "pytest", "-q", "--no-header", *tests],
                  cwd=repo_dir, timeout=600)

    # 2. pre-fix F2P must fail
    if apply_tp().returncode != 0:
        finish("test_patch does not apply")
    pre = run_tests(f2p)
    if pre.returncode == 0:
        revert_tp(); finish("F2P passes pre-fix (bad env)")

    # 3. gold check: official patch must make F2P pass
    g = sh(["git", "apply", "--whitespace=nowarn", "-"], cwd=repo_dir,
           input=inst["patch"])
    if g.returncode != 0:
        revert_tp(); finish("gold patch does not apply")
    gold = run_tests(f2p)
    sh(["git", "apply", "-R", "--whitespace=nowarn", "-"], cwd=repo_dir,
       input=inst["patch"])
    if gold.returncode != 0:
        revert_tp(); finish("gold patch does not fix F2P (env mismatch)")

    # 4. P2P baseline
    random.seed(0)
    sample = random.sample(p2p, min(10, len(p2p)))
    good = [t for t in sample if run_tests([t]).returncode == 0]
    revert_tp()
    if len(good) < 5:
        finish(f"only {len(good)}/10 P2P pass pre-fix")
    json.dump(good, open(f"{HERE}/baseline_{iid}.json", "w"))
    out["p2p_baseline"] = len(good)
    finish("validated", ok=True)

if __name__ == "__main__":
    main()

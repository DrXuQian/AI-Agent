#!/usr/bin/env python3
"""Apply official test_patch and run FAIL_TO_PASS + PASS_TO_PASS for an instance.
Usage: evaluate.py <instance_id> [--p2p-sample N]"""
import json, subprocess, sys, random

def main():
    iid = sys.argv[1]
    n_p2p = int(sys.argv[sys.argv.index("--p2p-sample")+1]) if "--p2p-sample" in sys.argv else 20
    inst = next(r for r in json.load(open(__file__.rsplit("/",1)[0]+"/instances.json"))
                if r["instance_id"] == iid)
    repo = f"{__file__.rsplit('/',1)[0]}/repos/{iid}"

    # The grader owns the test directories: drop any agent-made repro files or
    # test edits there before applying the official test patch.
    for d in ("tests", "testing"):
        subprocess.run(["git", "checkout", "--", d], cwd=repo, capture_output=True)
        subprocess.run(["git", "clean", "-qfd", d], cwd=repo, capture_output=True)
    # Apply official test patch (tests only — never touches the fix itself).
    subprocess.run(["git", "apply", "--whitespace=nowarn", "-"], cwd=repo,
                   input=inst["test_patch"], text=True, check=True)
    try:
        f2p = json.loads(inst["FAIL_TO_PASS"])
        p2p = json.loads(inst["PASS_TO_PASS"])
        random.seed(0)
        p2p_sample = random.sample(p2p, min(n_p2p, len(p2p)))

        def run(tests):
            r = subprocess.run([".venv/bin/python", "-m", "pytest", "-q", "--no-header",
                                *tests], cwd=repo, capture_output=True, text=True, timeout=600)
            return r

        import os
        base_file = f"{__file__.rsplit('/',1)[0]}/baseline_{iid}.json"
        if "--make-baseline" in sys.argv:
            # Record which P2P sample tests pass pre-fix; only those count later.
            good = [t for t in p2p_sample if run([t]).returncode == 0]
            json.dump(good, open(base_file, "w"))
            print(f"baseline: {len(good)}/{len(p2p_sample)} P2P tests pass pre-fix")
        if os.path.exists(base_file):
            p2p_sample = json.load(open(base_file))
        rf = run(f2p)
        rp = run(p2p_sample) if p2p_sample else None
        f2p_ok = rf.returncode == 0
        p2p_ok = rp is None or rp.returncode == 0
        print(f"F2P ({len(f2p)} tests): {'PASS' if f2p_ok else 'FAIL'}")
        print((rf.stdout + rf.stderr).strip().splitlines()[-1])
        print(f"P2P sample ({len(p2p_sample)} tests): {'PASS' if p2p_ok else 'FAIL'}")
        if rp: print((rp.stdout + rp.stderr).strip().splitlines()[-1])
        print("RESOLVED" if (f2p_ok and p2p_ok) else "NOT_RESOLVED")
    finally:
        # Revert the test patch so the workspace returns to the agent's state.
        subprocess.run(["git", "apply", "-R", "--whitespace=nowarn", "-"], cwd=repo,
                       input=inst["test_patch"], text=True)

if __name__ == "__main__":
    main()

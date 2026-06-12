#!/usr/bin/env python3
"""Grade a HumanEval+ solution against the EvalPlus test suite.
Usage: python3 grade.py <task_id> <solution_file>
The solution file must define entry_point. We exec: prompt-less solution + test + check(entry_point).
Exit 0 = PASS, 1 = FAIL. Prints PASS/FAIL.
"""
import json, os, sys, subprocess, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

def main():
    task_id = sys.argv[1]
    sol_path = sys.argv[2]
    inst = next(t for t in json.load(open(f"{HERE}/tasks.json")) if t["task_id"] == task_id)
    solution = open(sol_path).read()
    # EvalPlus test defines `def check(candidate)` and asserts; harness calls check(entry).
    harness = solution + "\n\n" + inst["test"] + f"\n\ncheck({inst['entry_point']})\n"
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(harness); path = f.name
    try:
        r = subprocess.run([sys.executable, path], capture_output=True, text=True, timeout=60)
        ok = r.returncode == 0
        print("PASS" if ok else "FAIL")
        if not ok:
            print((r.stdout + r.stderr).strip().splitlines()[-1] if (r.stdout+r.stderr).strip() else "no output")
        sys.exit(0 if ok else 1)
    except subprocess.TimeoutExpired:
        print("FAIL"); print("timeout"); sys.exit(1)
    finally:
        os.unlink(path)

if __name__ == "__main__":
    main()

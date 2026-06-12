#!/bin/bash
# Full 3-arm sweep over validated instances. Usage: run_full.sh <iid>
IID=$1
echo "##### $IID hybrid #####"
python3 swebench_hybrid.py "$IID"            && python3 evaluate.py "$IID" | tee "eval_${IID}_hybrid.txt"
echo "##### $IID baseline #####"
python3 swebench_hybrid.py "$IID" --no-delegate && python3 evaluate.py "$IID" | tee "eval_${IID}_baseline.txt"
echo "##### $IID localfirst #####"
python3 swebench_localfirst.py "$IID"        && python3 evaluate.py "$IID" | tee "eval_${IID}_localfirst.txt"
echo "LANE DONE $IID"

#!/bin/bash
IID=$1
python3 swebench_inflight.py "$IID" && python3 evaluate.py "$IID" > eval_${IID}_inflight.txt 2>&1
echo "IF DONE $IID"

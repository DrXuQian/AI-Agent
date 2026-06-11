#!/bin/bash
# Usage: run_lane.sh <instance_id>
IID=$1
for ARM_FLAG in "" "--no-delegate"; do
  ARM=$([ -z "$ARM_FLAG" ] && echo hybrid || echo baseline)
  echo "##### $IID $ARM #####"
  python3 swebench_hybrid.py "$IID" $ARM_FLAG
  echo "----- evaluating $IID $ARM -----"
  python3 evaluate.py "$IID" | tee "eval_${IID}_${ARM}.txt"
done
echo "LANE DONE $IID"

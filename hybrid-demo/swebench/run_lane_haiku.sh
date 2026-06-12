#!/bin/bash
# Haiku-as-worker lane (MiniMax-M2-class proxy): hybrid + localfirst arms.
IID=$1
export WORKER_MODEL=claude-haiku-4-5
export ARM_TAG=_haiku
echo "##### $IID hybrid(haiku) #####"
python3 swebench_hybrid.py "$IID" && python3 evaluate.py "$IID" | tee "eval_${IID}_hybrid_haiku.txt"
echo "##### $IID localfirst(haiku) #####"
python3 swebench_localfirst.py "$IID" && python3 evaluate.py "$IID" | tee "eval_${IID}_localfirst_haiku.txt"
echo "LANE DONE $IID"

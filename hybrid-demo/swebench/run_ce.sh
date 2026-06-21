#!/bin/bash
IID=$1
echo "##### $IID baseline(opus) #####"
CLOUD_MODEL=claude-opus-4-8 ARM_TAG=_opus python3 swebench_hybrid.py "$IID" --no-delegate \
  && python3 evaluate.py "$IID" > eval_${IID}_baseline_opus.txt 2>&1
echo "##### $IID context-engine #####"
python3 swebench_context_engine.py "$IID" \
  && python3 evaluate.py "$IID" > eval_${IID}_ctxengine.txt 2>&1
echo "LANE DONE $IID"

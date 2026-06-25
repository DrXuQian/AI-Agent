#!/bin/bash
# Four-card tier: Opus-4.6 as the (free) local worker, Opus-4.8 cloud.
IID=$1
export WORKER_MODEL=claude-opus-4-6 ARM_TAG=_4card
echo "##### $IID context-engine(opus46) #####"
python3 swebench_context_engine.py "$IID" && python3 evaluate.py "$IID" > eval_${IID}_ctxengine_4card.txt 2>&1
echo "##### $IID escalate(opus46) #####"
python3 swebench_escalate.py "$IID" && python3 evaluate.py "$IID" > eval_${IID}_escalate_4card.txt 2>&1
echo "LANE DONE $IID"

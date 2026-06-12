#!/bin/bash
# Escalation lanes: sonnet-worker and haiku-worker variants, per instance.
IID=$1
echo "##### $IID escalate (sonnet worker) #####"
WORKER_MODEL=claude-sonnet-4-6 ARM_TAG="" python3 swebench_escalate.py "$IID" \
  && python3 evaluate.py "$IID" | tee "eval_${IID}_escalate.txt"
echo "##### $IID escalate (haiku worker) #####"
WORKER_MODEL=claude-haiku-4-5 ARM_TAG=_haiku python3 swebench_escalate.py "$IID" \
  && python3 evaluate.py "$IID" | tee "eval_${IID}_escalate_haiku.txt"
echo "LANE DONE $IID"

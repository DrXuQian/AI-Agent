#!/bin/bash
IID=$1
for arm in baseline escalate localfirst; do
  ARM=$arm python3 run.py "$IID" 2>>err_$arm.log
done

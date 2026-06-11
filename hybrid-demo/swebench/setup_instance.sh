#!/bin/bash
# Usage: setup_instance.sh <instance_id> <repo> <base_commit>
set -e
IID=$1; REPO=$2; COMMIT=$3
DIR="repos/$IID"
if [ ! -d "$DIR/.git" ]; then
  git clone --filter=blob:none "https://github.com/$REPO" "$DIR"
fi
cd "$DIR"
git checkout -q -f "$COMMIT"
git clean -qfd
python3 -m venv .venv 2>/dev/null || true
.venv/bin/pip install -q -e . pytest 2>&1 | tail -1
echo "OK $IID"

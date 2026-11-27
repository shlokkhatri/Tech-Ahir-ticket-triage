#!/usr/bin/env bash
# Mac/Linux: ./run.sh      (add --mock to test without a key)
set -e
cd "$(dirname "$0")"
[ -d venv ] || python3 -m venv venv
source venv/bin/activate
pip install -q -r requirements.txt
python main.py "$@"

#!/usr/bin/env bash
set -eu
cd "$LHB_WS"
python3 "$(dirname "$0")/build.py" "$LHB_WS"

#!/usr/bin/env bash
set -eu
cd "$LHB_WS"
mkdir -p out state
i=0
while :; do
  i=$((i + 1))
  if sh bin/scan data/input.txt > out/scan.txt 2> state/scan.err; then
    break
  fi
  if [ "$i" -ge 6 ]; then
    cat state/scan.err >&2
    exit 1
  fi
done
python3 "$(dirname "$0")/build_report.py" "$LHB_WS"

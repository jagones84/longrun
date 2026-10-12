#!/usr/bin/env bash
# Longrun regression battery — Auto-discovered tests.
# Run:  bash tests/battery.sh
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1

TMP="$(mktemp -d "${TMPDIR:-/tmp}/sf-battery-XXXXXX")"
export PYTHONPYCACHEPREFIX="$TMP/pyc"
export LONGRUN_CONFIG_DIR="$TMP/cfg"
export LONGRUN_SESSIONS_DIR="$TMP/sessions"
export LONGRUN_DB="$TMP/events.db"
export LONGRUN_GRAPH_DIR="$TMP/graphs"
export LONGRUN_EDITS_DIR="$TMP/edits"
export LONGRUN_RUNS_DIR="$TMP/runs"
export LONGRUN_ROLES_DIR="$TMP/roles"
export LONGRUN_COSTS_DIR="$TMP/costs"
export LONGRUN_THREADS_DIR="$TMP/threads"
export LONGRUN_PRICES_FILE="$TMP/prices.json"
mkdir -p "$LONGRUN_CONFIG_DIR" "$LONGRUN_SESSIONS_DIR" \
         "$LONGRUN_GRAPH_DIR" "$LONGRUN_EDITS_DIR" "$LONGRUN_RUNS_DIR" \
         "$LONGRUN_ROLES_DIR" "$LONGRUN_COSTS_DIR" "$LONGRUN_THREADS_DIR"

fail=0
total=0
pass=0

# Auto-discover tests in tests/acceptance
for t in tests/acceptance/v*.py; do
  total=$((total + 1))
  name=$(basename "$t" .py)
  echo "=== $name ==="
  if python3 "$t"; then
    echo "PASS $name"
    pass=$((pass + 1))
  else
    echo "FAIL $name"
    fail=1
  fi
done

rm -rf "$TMP"

if [ "$fail" -eq 0 ]; then
  echo "=== battery: $pass/$total GREEN ==="
else
  echo "=== battery: $pass/$total (FAILURES — see above) ==="
fi
exit "$fail"

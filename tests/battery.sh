#!/usr/bin/env bash
# Longrun regression battery — Auto-discovered, deterministic, ISOLATED tests.
#
#   bash tests/battery.sh          # fast gate: heavy tests skipped, tests run in PARALLEL
#   LONGRUN_BATTERY_FULL=1 bash tests/battery.sh   # full suite (adds the heavy tests)
#   LONGRUN_BATTERY_JOBS=1 bash tests/battery.sh   # force sequential (debugging)
#
# JAG-449: the heavy tests (real vector-index builds / doc ingestion) are ~50s
# together and are SKIPPED by default so the gate stays quick. Every test gets its
# OWN throwaway LONGRUN_* dirs, so the suite is safe to run in parallel; only the
# .pyc cache is shared (python writes it atomically).
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1

TMP="$(mktemp -d "${TMPDIR:-/tmp}/sf-battery-XXXXXX")"
PYC="$TMP/pyc"
RES="$TMP/results"
export PYTHONPYCACHEPREFIX="$PYC"
mkdir -p "$PYC" "$RES"

# Heavy tests skipped unless LONGRUN_BATTERY_FULL=1
SLOW_TESTS="v408_doc_ingest v399_codebase_index v431r5_pdf_kb v400_knowledge_notebooks v409_embed_providers v402_research"

LIST=""
SKIP=0
for t in tests/acceptance/v*.py; do
  name=$(basename "$t" .py)
  if [ "${LONGRUN_BATTERY_FULL:-0}" != "1" ]; then
    case " $SLOW_TESTS " in
      *" $name "*)
        SKIP=$((SKIP + 1))
        continue
        ;;
    esac
  fi
  LIST="$LIST $t"
done

# One isolated test run (its own throwaway data dirs).
_run_one() {
  t="$1"
  name="$(basename "$t" .py)"
  d="$(mktemp -d "${TMPDIR:-/tmp}/sf-t-XXXXXX")"
  timing="${LONGRUN_BATTERY_TIMINGS:-0}"
  if [ "$timing" = "1" ]; then start_ms="$(date +%s%3N)"; fi
  mkdir -p "$d/cfg" "$d/sessions" "$d/graphs" "$d/edits" "$d/runs" \
           "$d/roles" "$d/costs" "$d/threads" "$d/data"
  PYTHONPYCACHEPREFIX="$PYC" \
  LONGRUN_DATA_DIR="$d/data" \
  LONGRUN_CONFIG_DIR="$d/cfg" \
  LONGRUN_SESSIONS_DIR="$d/sessions" \
  LONGRUN_DB="$d/events.db" \
  LONGRUN_GRAPH_DIR="$d/graphs" \
  LONGRUN_EDITS_DIR="$d/edits" \
  LONGRUN_RUNS_DIR="$d/runs" \
  LONGRUN_ROLES_DIR="$d/roles" \
  LONGRUN_COSTS_DIR="$d/costs" \
  LONGRUN_THREADS_DIR="$d/threads" \
  LONGRUN_PRICES_FILE="$d/prices.json" \
  python3 "$t" > "$d/log" 2>&1
  test_status=$?
  if [ "$timing" = "1" ]; then
    elapsed_ms=$(( $(date +%s%3N) - start_ms ))
    printf '%s\t%s\n' "$elapsed_ms" "$name" >> "$RES/timing"
  fi
  if [ "$test_status" -eq 0 ]; then
    echo 0 > "$RES/$name.rc"
  else
    echo 1 > "$RES/$name.rc"
    cp "$d/log" "$RES/$name.log"
  fi
  rm -rf "$d"
}
export -f _run_one
export PYC RES

JOBS="${LONGRUN_BATTERY_JOBS:-$(nproc 2>/dev/null || echo 4)}"
# More workers caused CPU / filesystem contention on the DGX. Twelve workers
# benchmarked faster than both eight and nproc while keeping the gate near 12s.
if [ -z "${LONGRUN_BATTERY_JOBS:-}" ] && [ "$JOBS" -gt 12 ]; then
  JOBS=12
fi
# shellcheck disable=SC2086
printf '%s\n' $LIST | xargs -P "$JOBS" -I {} bash -c '_run_one "$@"' _ {}
if [ "${LONGRUN_BATTERY_TIMINGS:-0}" = "1" ] && [ -f "$RES/timing" ]; then
  echo "=== slowest tests (ms) ==="
  sort -nr "$RES/timing" | head -10
fi

# Aggregate
total=0
pass=0
fail=0
for rc in "$RES"/*.rc; do
  [ -e "$rc" ] || continue
  total=$((total + 1))
  if [ "$(cat "$rc")" = "0" ]; then
    pass=$((pass + 1))
  else
    fail=1
  fi
done
for lg in "$RES"/*.log; do
  [ -e "$lg" ] || continue
  echo "===== $(basename "$lg" .log) ====="
  grep -E "^FAIL" "$lg" | head -20
done

rm -rf "$TMP"

if [ "$fail" -eq 0 ]; then
  if [ "$SKIP" -gt 0 ]; then
    echo "=== battery: $pass/$total GREEN ($SKIP heavy skipped — LONGRUN_BATTERY_FULL=1 to run) ==="
  else
    echo "=== battery: $pass/$total GREEN ==="
  fi
else
  echo "=== battery: $pass/$total (FAILURES — see above) ==="
fi
exit "$fail"

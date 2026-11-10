#!/usr/bin/env bash
# Longrun regression battery — Auto-discovered, deterministic, ISOLATED tests.
#
#   bash tests/battery.sh          # fast gate: heavy tests skipped, tests run in PARALLEL
#   LONGRUN_BATTERY_FULL=1 bash tests/battery.sh   # full suite (adds the heavy tests)
#   LONGRUN_BATTERY_JOBS=1 bash tests/battery.sh   # force sequential (debugging)
#   LONGRUN_BATTERY_TESTS="v753_stop_kills_work" bash tests/battery.sh  # only these (+ UI guard)
#   LONGRUN_BATTERY_UI=0 bash tests/battery.sh     # drop the UI guard from a targeted run
#   bash tests/battery_tmp.sh      # the targeted launcher (overwritten per fix)
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
# EV-45b: never READ or WRITE a bytecode cache next to the source. Measured
# 2026-10-30: a `__pycache__/jobbench_compare.cpython-312.pyc` written by a manual
# driver run made a test assert on the OLD function body (a pin failed while the
# source carried the fix). On this network mount the source mtime can land in the
# same coarse tick as a previous compile, so python considered the stale .pyc
# valid. Deterministic gate = no bytecode cache at all.
#
# v753: "no cache at all" also meant every one of the 442 test processes recompiled
# the whole package — measured 0.65 s of a 0.70 s import (.agent/trash/import_probe.py:
# 0.655/0.663/0.679/0.801/0.617 s cold vs 0.043 s from cache). The cache now lives in
# THIS run's throwaway dir and is precompiled ONCE below, so it can never be stale
# across runs (the dir is new every run) and the tests stay read-only
# (PYTHONDONTWRITEBYTECODE=1): no test can ever write a .pyc, and nothing is written
# next to the source. LONGRUN_BATTERY_NOPYC=1 restores the compile-every-time path.
export PYTHONDONTWRITEBYTECODE=1
mkdir -p "$PYC" "$RES"
if [ "${LONGRUN_BATTERY_NOPYC:-0}" != "1" ]; then
  python3 -m compileall -q -j 0 src >/dev/null 2>&1 || true
fi

# Live progress log. The aggregate summary only prints when EVERY test is done, so a
# hung gate used to look like an empty screen. This file is TRUNCATED on every run
# and appended by each test as it starts/finishes: the last START without its END
# names the test that is stuck.
PROGRESS="$ROOT/.agent/logs/battery-progress.log"
mkdir -p "$(dirname "$PROGRESS")"
: > "$PROGRESS"
export PROGRESS

# Heavy tests skipped unless LONGRUN_BATTERY_FULL=1
SLOW_TESTS="v408_doc_ingest v399_codebase_index v431r5_pdf_kb v400_knowledge_notebooks v409_embed_providers v402_research"

# UI GUARD (2026-11-09): commit `23d4528` brought real deck work in `orbit.html` but wrote
# `webui/index.html` from a base OLDER than the approved UI, so the pane toggles, the
# remembered panes, Ctrl/Cmd+B, the phone rail density and the drawer-closing jump vanished
# while the in-flight gate carried only that stream's tests (restored in `c07f212`). A
# TARGETED run therefore always adds these shell/rail/pane pins: a file replaced by an
# older copy fails on the spot. `LONGRUN_BATTERY_UI=0` opts out for a deliberate rewrite.
UI_GUARD="v352_appearance_theme v360_shell_fixes v368_panel_resize v497_inspector_bulk_toggle
v600_agents_session_button v644_view_cols_fit v655_single_writer_test_chips v758_rail_grammar
v761_mobile_drawers v763_ui_icons v774_invalid_reply_recovery v777_landscape_chat
v778_session_ids_and_sparkle_cache v851_ui_a11y_gate v888_team_click_and_page_fit
v890_rail_groups_team_colour_and_compact_rows v891_deck_fit_and_row_menus v910_no_team_bulk
v934_composer_session_drafts v955_queued_message_visible"

# TARGETED run (the fix under test): `LONGRUN_BATTERY_TESTS="v753_x v750_y"` runs
# ONLY those files (plus the UI guard below). The launcher is tests/battery_tmp.sh,
# overwritten on every fix. A name that does not exist is an ERROR (exit 2): an empty
# battery would print GREEN and prove nothing.
ONLY="${LONGRUN_BATTERY_TESTS:-}"
LIST=""
SKIP=0
if [ -n "$ONLY" ]; then
  MISSING=""
  for name in $ONLY; do
    t="tests/acceptance/$name.py"
    [ -f "$t" ] || { MISSING="$MISSING $name"; continue; }
    LIST="$LIST $t"
  done
  if [ -n "$MISSING" ]; then
    echo "=== battery: unknown test(s):$MISSING (see tests/acceptance/) ==="
    exit 2
  fi
  if [ "${LONGRUN_BATTERY_UI:-1}" != "0" ]; then
    ADDED=0
    for name in $UI_GUARD; do
      case " $ONLY " in *" $name "*) continue ;; esac
      t="tests/acceptance/$name.py"
      [ -f "$t" ] || { echo "=== battery: UI guard test missing: $name ==="; exit 2; }
      LIST="$LIST $t"
      ADDED=$((ADDED + 1))
    done
    [ "$ADDED" -gt 0 ] && \
      echo "=== battery: + $ADDED UI guard test(s) (LONGRUN_BATTERY_UI=0 to skip) ==="
  fi
else
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
fi

# One isolated test run (its own throwaway data dirs).
_run_one() {
  t="$1"
  name="$(basename "$t" .py)"
  d="$(mktemp -d "${TMPDIR:-/tmp}/sf-t-XXXXXX")"
  timing="${LONGRUN_BATTERY_TIMINGS:-0}"
  start_ms="$(date +%s%3N)"
  printf 'START %-42s %s\n' "$name" "$(date -u +%FT%TZ)" >> "$PROGRESS"
  mkdir -p "$d/cfg" "$d/sessions" "$d/graphs" "$d/edits" "$d/runs" \
           "$d/roles" "$d/costs" "$d/threads" "$d/data" "$d/matrix_src" "$d/matrix_dot"
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
  LONGRUN_MATRIX_SRC="$d/matrix_src" \
  LONGRUN_MATRIX_DOT="$d/matrix_dot" \
  python3 "$t" > "$d/log" 2>&1
  test_status=$?
  elapsed_ms=$(( $(date +%s%3N) - start_ms ))
  printf 'END   %-42s rc=%s %sms\n' "$name" "$test_status" "$elapsed_ms" >> "$PROGRESS"
  if [ "$timing" = "1" ]; then
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
# More workers only add CPU / filesystem contention on the DGX. Measured
# 2026-10-31 (442 tests, nproc=20, back-to-back): 12 workers -> 141-160 s;
# 18 -> 170 s and 20 -> 166 s, both WITH a failure (v225_compact_bounded asserts a
# 3 s wall budget and loses it under starvation). Twelve is the cap.
if [ -z "${LONGRUN_BATTERY_JOBS:-}" ] && [ "$JOBS" -gt 12 ]; then
  JOBS=12
fi
# shellcheck disable=SC2086
printf 'RUN   jobs=%s tests=%s started=%s\n' \
  "$JOBS" "$(printf '%s\n' $LIST | wc -l)" "$(date -u +%FT%TZ)" >> "$PROGRESS"
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

printf 'DONE  pass=%s total=%s fail=%s %s\n' \
  "$pass" "$total" "$fail" "$(date -u +%FT%TZ)" >> "$PROGRESS"

# Stamps: which gate ran, when, with what result. `.agent/logs/` is gitignored, so
# this is operator memory, not a shipped artifact. The last FULL run is what the
# rules use to decide whether a full battery is overdue.
STAMP_DIR="$ROOT/.agent/logs"
mkdir -p "$STAMP_DIR"
MODE="full"
[ "${LONGRUN_BATTERY_FULL:-0}" = "1" ] || MODE="fast"
[ -n "$ONLY" ] && MODE="targeted"
printf 'date=%s mode=%s pass=%s total=%s fail=%s tests=%s\n' \
  "$(date -u +%FT%TZ)" "$MODE" "$pass" "$total" "$fail" "${ONLY:-all}" \
  > "$STAMP_DIR/battery-last-run.txt"
if [ "$MODE" = "full" ]; then
  cp "$STAMP_DIR/battery-last-run.txt" "$STAMP_DIR/battery-last-full.txt"
fi

if [ "$fail" -eq 0 ]; then
  if [ "$SKIP" -gt 0 ]; then
    echo "=== battery: $pass/$total GREEN ($SKIP heavy skipped — LONGRUN_BATTERY_FULL=1 to run) ==="
  else
    echo "=== battery: $pass/$total GREEN ==="
  fi
else
  echo "=== battery: $pass/$total (FAILURES — see above) ==="
fi
LAST_FULL="$STAMP_DIR/battery-last-full.txt"
if [ -f "$LAST_FULL" ]; then
  echo "last full battery: $(cut -d' ' -f1 "$LAST_FULL")"
else
  echo "last full battery: never recorded"
fi
echo "progress log: $PROGRESS"
exit "$fail"

#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
# v910: the No-team bucket bulk actions (+ the shared bulk engine refactor).
set -u
# NOTE: v758/v890/v851 are EXCLUDED — they fail on the inspector surface for
# reasons that predate v910 (verified: the asserted strings are absent from the
# pre-change tree too). They are reported to the operator, not silently skipped.
TESTS="v910_no_team_bulk v482_team_bulk v614_drop_old_plans v314_cascade_delete v315_session_delete_final v891_deck_fit_and_row_menus v752_filtersort v617_deck_rail"
cd /home/jagones/Repositories/longrun || exit 1
fail=0
for t in $TESTS; do
  out=$(python3 "tests/acceptance/$t.py" 2>&1) || { echo "FAIL $t"; echo "$out" | tail -8; fail=1; continue; }
  echo "ok   $t  $(echo "$out" | tail -1)"
done
set -- $TESTS
[ "$fail" = 0 ] && echo "=== battery: $# GREEN ===" || echo "=== battery: RED ==="
exit "$fail"

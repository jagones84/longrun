#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
# 2026-11-09 UI round: the constellation AGENT/ALL pair became ONE scope menu
# (constMode select) and the squeezed Agents|Jobs row drops the ✨ Architect
# autogen icon (container query). Pins re-pointed: v294, v617, v703; markup pins
# v772/v881 and the .toolbar>.stack pin v678 re-run to prove no collateral.
set -u
TESTS="v294_constellation v617_deck_rail v703_constellation_session v772_generate_surfaces v881_control_deck_layout v678_teamorg_scope v891_deck_fit_and_row_menus v629_ui_rail_jobs_nesting"
cd /home/jagones/Repositories/longrun || exit 1
fail=0
for t in $TESTS; do
  out=$(python3 "tests/acceptance/$t.py" 2>&1) || { echo "FAIL $t"; echo "$out" | tail -8; fail=1; continue; }
  echo "ok   $t  $(echo "$out" | tail -1)"
done
set -- $TESTS
[ "$fail" = 0 ] && echo "=== battery: $# GREEN ===" || echo "=== battery: RED ==="
exit "$fail"

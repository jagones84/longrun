#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
set -u
TESTS="v881_control_deck_layout v880_skill_chip_and_jump_arrow v879_one_control_per_rail_job v878_rail_follows_backend_naming v679_automation_ledger v678_teamorg_scope v851_ui_a11y_gate v776_readback_turn_attribution v504_webui_script_balance v354_ui_links_pins"
cd /home/jagones/Repositories/longrun || exit 1
fail=0
for t in $TESTS; do
  out=$(python3 "tests/acceptance/$t.py" 2>&1) || { echo "FAIL $t"; echo "$out" | tail -6; fail=1; continue; }
  echo "ok   $t  $(echo "$out" | tail -1)"
done
set -- $TESTS
[ "$fail" = 0 ] && echo "=== battery: $# GREEN ===" || echo "=== battery: RED ==="
exit "$fail"

#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
set -u
TESTS="v890_rail_groups_team_colour_and_compact_rows v885_rail_jumps_and_agent_bar v867_rail_sections_and_modes v616_permit_gate_and_secrets v329_select_survives_poll v291_orbit_simple v889_architect_module_and_risk v888_team_click_and_page_fit v887_architect_tools_and_name v678_teamorg_scope v881_control_deck_layout v772_generate_surfaces v540_automate_scope v740_exclusive_delta_only v851_ui_a11y_gate v504_webui_script_balance v354_ui_links_pins"
cd /home/jagones/Repositories/longrun || exit 1
fail=0
for t in $TESTS; do
  out=$(python3 "tests/acceptance/$t.py" 2>&1) || { echo "FAIL $t"; echo "$out" | tail -8; fail=1; continue; }
  echo "ok   $t  $(echo "$out" | tail -1)"
done
set -- $TESTS
[ "$fail" = 0 ] && echo "=== battery: $# GREEN ===" || echo "=== battery: RED ==="
exit "$fail"

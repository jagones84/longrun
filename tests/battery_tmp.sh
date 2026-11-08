#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
set -u
TESTS="v889_architect_module_and_risk v888_team_click_and_page_fit v887_architect_tools_and_name v678_teamorg_scope v881_control_deck_layout v679_automation_ledger v772_generate_surfaces v537_exclusive_tool_objects v540_automate_scope v618_permit_shell_bypass v629_ui_rail_jobs_nesting v663_retest_residues v735_index_and_media v738_batch_shape_readonly_gate_voice v740_exclusive_delta_only v767_agent_workspace_subtree v527_prices_refresh v851_ui_a11y_gate v504_webui_script_balance v354_ui_links_pins"
cd /home/jagones/Repositories/longrun || exit 1
fail=0
for t in $TESTS; do
  out=$(python3 "tests/acceptance/$t.py" 2>&1) || { echo "FAIL $t"; echo "$out" | tail -8; fail=1; continue; }
  echo "ok   $t  $(echo "$out" | tail -1)"
done
set -- $TESTS
[ "$fail" = 0 ] && echo "=== battery: $# GREEN ===" || echo "=== battery: RED ==="
exit "$fail"

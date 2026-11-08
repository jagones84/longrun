#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
set -u
TESTS="v895_attached_panes_and_fitted_columns v894_automate_scroll_popover_close_panel_clip v893_org_links_and_stacked_identity v892_tight_table_and_hard_right_edge v891_deck_fit_and_row_menus v890_rail_groups_team_colour_and_compact_rows v885_rail_jumps_and_agent_bar v482_team_bulk v536_ui_edit_parity v678_teamorg_scope v881_control_deck_layout v335_job_rows v311_controls_clear_rename_delete v619_deck_feed_and_fullheight v437_orbit_mobile_touch v622_custom_views v629_ui_rail_jobs_nesting v867_rail_sections_and_modes v616_permit_gate_and_secrets v329_select_survives_poll v291_orbit_simple v851_ui_a11y_gate v504_webui_script_balance v354_ui_links_pins v404_run_cost_ui v624_operator_round2 v626_view_row_layout"
cd /home/jagones/Repositories/longrun || exit 1
fail=0
for t in $TESTS; do
  out=$(python3 "tests/acceptance/$t.py" 2>&1) || { echo "FAIL $t"; echo "$out" | tail -8; fail=1; continue; }
  echo "ok   $t  $(echo "$out" | tail -1)"
done
set -- $TESTS
[ "$fail" = 0 ] && echo "=== battery: $# GREEN ===" || echo "=== battery: RED ==="
exit "$fail"

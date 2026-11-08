#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
set -u
TESTS="v905_agent_jobs_lane v904_reply_not_markup v630_ui_meta_stack v851_ui_a11y_gate v291_orbit_simple v679_automation_ledger v772_generate_surfaces v890_rail_groups_team_colour_and_compact_rows v899_frameless_controls_and_policy_feedback v340_team_scope v534_longrun_agent_veo v897_team_role_md_and_aligned_heads v896_model_label_priority v895_attached_panes_and_fitted_columns v894_automate_scroll_popover_close_panel_clip v893_org_links_and_stacked_identity v892_tight_table_and_hard_right_edge v891_deck_fit_and_row_menus v887_architect_tools_and_name v885_rail_jumps_and_agent_bar v881_control_deck_layout v678_teamorg_scope v629_ui_rail_jobs_nesting v626_view_row_layout v619_deck_feed_and_fullheight v540_automate_scope v537_exclusive_tool_objects v536_ui_edit_parity v404_run_cost_ui v335_job_rows v329_select_survives_poll v311_controls_clear_rename_delete v886_teamorg_relations_and_team_toggle v511_ui_cot_slash_camera v324_subjob_hierarchy v290_job_deps v287_routines_budget v752_filtersort v631_rail_toolbar v294_constellation"
cd /home/jagones/Repositories/longrun || exit 1
fail=0
for t in $TESTS; do
  out=$(python3 "tests/acceptance/$t.py" 2>&1) || { echo "FAIL $t"; echo "$out" | tail -8; fail=1; continue; }
  echo "ok   $t  $(echo "$out" | tail -1)"
done
set -- $TESTS
[ "$fail" = 0 ] && echo "=== battery: $# GREEN ===" || echo "=== battery: RED ==="
exit "$fail"

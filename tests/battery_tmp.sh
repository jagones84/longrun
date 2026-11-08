#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
set -u
TESTS="v904_reply_not_markup v303_job_delegation v369_dsml_tool_calls v501_fs_find v843_step_action_gate v751_argkv_tool_dialect v769_harness_trace_truthfulness v875_sessions_wait_reply v304_json_artifact v902_job_completion_notice v903_detached_dispatch v322_job_delegation_subjobs v336_complex_organigram v629_ui_rail_jobs_nesting v324_subjob_hierarchy v334_nested_subjob_ids v338_master_autonomy v326_subjob_natural_order v450_team_dispatch v310_agent_turn_delivery"
cd /home/jagones/Repositories/longrun || exit 1
fail=0
for t in $TESTS; do
  out=$(python3 "tests/acceptance/$t.py" 2>&1) || { echo "FAIL $t"; echo "$out" | tail -8; fail=1; continue; }
  echo "ok   $t  $(echo "$out" | tail -1)"
done
set -- $TESTS
[ "$fail" = 0 ] && echo "=== battery: $# GREEN ===" || echo "=== battery: RED ==="
exit "$fail"

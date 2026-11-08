#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
set -u
TESTS="v900_subagent_step_budget v451_subagents_panel v563_subagent_run_budget v577_spawn_budget_dispatch v672_subagent_tool_scope v569_acceptance_predicates v529_session_jobs v140_subagent_todos v827_context_limits_config v528_parallel_batch v488_config_editor v728_jobbench_external_arms v886_teamorg_relations_and_team_toggle v647_meta_tools_truth"
cd /home/jagones/Repositories/longrun || exit 1
fail=0
for t in $TESTS; do
  out=$(python3 "tests/acceptance/$t.py" 2>&1) || { echo "FAIL $t"; echo "$out" | tail -8; fail=1; continue; }
  echo "ok   $t  $(echo "$out" | tail -1)"
done
set -- $TESTS
[ "$fail" = 0 ] && echo "=== battery: $# GREEN ===" || echo "=== battery: RED ==="
exit "$fail"

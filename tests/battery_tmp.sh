#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
set -u
TESTS="v902_job_completion_notice v903_detached_dispatch v310_agent_turn_delivery v450_team_dispatch v507_namespaced_subtools v613_session_tools v674_send_idempotency v581_team_fixes_b v577_spawn_budget_dispatch v582_batch_dispatch v618_permit_shell_bypass v901_team_jobs_for_coordinators v795_steer_durable_visible v807_bgjob_announce"
cd /home/jagones/Repositories/longrun || exit 1
fail=0
for t in $TESTS; do
  out=$(python3 "tests/acceptance/$t.py" 2>&1) || { echo "FAIL $t"; echo "$out" | tail -8; fail=1; continue; }
  echo "ok   $t  $(echo "$out" | tail -1)"
done
set -- $TESTS
[ "$fail" = 0 ] && echo "=== battery: $# GREEN ===" || echo "=== battery: RED ==="
exit "$fail"

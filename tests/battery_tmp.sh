#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
set -u
TESTS="v909_approval_trim_keeps_pending v565_taint_standing_approval v567_consumable_approval v593_run_bound_approval v618_permit_shell_bypass v668_chat_taint v846_approval_fatigue v806_permissions_split v318_ckpt_approvals_delete v195_hard v386_shell_cwd v419_api_parity"
cd /home/jagones/Repositories/longrun || exit 1
fail=0
for t in $TESTS; do
  out=$(python3 "tests/acceptance/$t.py" 2>&1) || { echo "FAIL $t"; echo "$out" | tail -8; fail=1; continue; }
  echo "ok   $t  $(echo "$out" | tail -1)"
done
set -- $TESTS
[ "$fail" = 0 ] && echo "=== battery: $# GREEN ===" || echo "=== battery: RED ==="
exit "$fail"

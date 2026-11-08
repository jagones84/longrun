#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
set -u
TESTS="v504_webui_script_balance v536_ui_edit_parity v534_longrun_agent_veo v616_permit_gate_and_secrets v901_team_jobs_for_coordinators v618_permit_shell_bypass"
cd /home/jagones/Repositories/longrun || exit 1
fail=0
for t in $TESTS; do
  out=$(python3 "tests/acceptance/$t.py" 2>&1) || { echo "FAIL $t"; echo "$out" | tail -8; fail=1; continue; }
  echo "ok   $t  $(echo "$out" | tail -1)"
done
set -- $TESTS
[ "$fail" = 0 ] && echo "=== battery: $# GREEN ===" || echo "=== battery: RED ==="
exit "$fail"

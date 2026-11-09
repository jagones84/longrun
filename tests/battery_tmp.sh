#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
# v924/v925/v926: the termination-truth family (truncated subjob, honest run finalize,
# restart keeps dependents blocked) + their neighbours (SJ engine, JAG-462 finalize/abort,
# jobs wake/dependency semantics, run termination contracts).
set -u
TESTS="v924_truncated_subjob_not_dependency v925_run_graph_completion_truth v926_restart_keeps_dependents_blocked v529_session_jobs v459_jag462_sweep v289_job_ops v290_job_deps v348_job_dep_no_deadlock v901_team_jobs_for_coordinators v902_job_completion_notice v903_detached_dispatch v464_paperclip_run_outcome v590_interrupt_classify v325_phantom_run_all_paths v471_run_session_model_truth v664_run_manifest"
cd /home/jagones/Repositories/longrun || exit 1
fail=0
for t in $TESTS; do
  out=$(python3 "tests/acceptance/$t.py" 2>&1) || { echo "FAIL $t"; echo "$out" | tail -8; fail=1; continue; }
  echo "ok   $t  $(echo "$out" | tail -1)"
done
set -- $TESTS
[ "$fail" = 0 ] && echo "=== battery: $# GREEN ===" || echo "=== battery: RED ==="
exit "$fail"

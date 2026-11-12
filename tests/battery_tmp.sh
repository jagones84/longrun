#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
# 2026-11-13 RSI-W: a routine operation (save the tool policy, reload, save in another
# domain, compact) must not disable the approval gate. v822 pins the overlay/inheritance
# semantics the save goes through; v565/v593/v744/v909/v942 are the approval pins.
set -u
cd /home/jagones/Repositories/longrun || exit 1
LONGRUN_BATTERY_TESTS="v964_routine_ops_approval v822_subtool_policy_inheritance v565_taint_standing_approval v593_run_bound_approval v744_artifact_verification_policy v909_approval_trim_keeps_pending v942_git_readonly_autapprove" \
  bash tests/battery.sh

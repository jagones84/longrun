#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
# 2026-11-10 v952: the streaming worker releases the turn lock it ACQUIRED (bound),
# and a raising `turn_end` cannot skip that release. v419/v422/v729 pin the streaming
# path's shape and behaviour; v354 pins the README badge count; the UI guard proves
# the shell/rail/pane contract did not move.
set -u
cd /home/jagones/Repositories/longrun || exit 1
LONGRUN_BATTERY_TESTS="v952_turn_lock_after_delete v729_headless_turn v422_harness_audit_fixes v419_api_parity v354_ui_links_pins" \
  bash tests/battery.sh

#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
# 2026-11-11 v962: on mobile/PWA the token ask is the app's own dialog, a stored-but-
# rejected token re-asks, and the probe is bounded; v390/v493 pin the PWA + first-run
# surfaces this changed, v354 pins the README badge count, the UI guard proves the
# shell/rail/pane contract did not move.
set -u
cd /home/jagones/Repositories/longrun || exit 1
LONGRUN_BATTERY_TESTS="v962_mobile_token_ask v390_pwa v493_first_run_token v354_ui_links_pins" \
  bash tests/battery.sh

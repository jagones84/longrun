#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
# 2026-11-10 v951: the tool-result scrubber knows the webhook store's secrets and
# redacts a URL userinfo credential. v616 is the scrubber's own pin; v354 is the
# README badge count; the UI guard proves the shell/rail/pane contract did not move.
set -u
cd /home/jagones/Repositories/longrun || exit 1
LONGRUN_BATTERY_TESTS="v616_permit_gate_and_secrets v951_scrub_file_secrets v354_ui_links_pins" \
  bash tests/battery.sh

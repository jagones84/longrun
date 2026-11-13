#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
# 2026-11-13 HD-4: the SWE arm refuses an instance the gold patch cannot pass (the screen
# gate). v970 is the new pin; v842 owns the same module's provenance line; v354 pins the
# README badge bumped by the new test.
set -u
cd /home/jagones/Repositories/longrun || exit 1
LONGRUN_BATTERY_TESTS="v970_swe_screen_gate v842_bench_session_provenance v354_ui_links_pins" \
  bash tests/battery.sh

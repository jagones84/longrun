#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
# 2026-11-14 v972: the machine-written memory kinds bound themselves (a near-duplicate
# supersedes the stored copy; the excess above `memory_max_records` is superseded, lowest
# value first). The other names are the dependency oracle for that edit: the tombstone /
# supersession / dedupe / recall paths the write path now calls, the health report it
# extended, the config owner the budget comes from, and v354 which pins the README badge.
set -u
cd /home/jagones/Repositories/longrun || exit 1
LONGRUN_BATTERY_TESTS="v972_memory_hygiene v204_memory_governance v628_memory_supersession v853_prompt_memory_dedupe_budget v819_memory_kinds v876_memory_weak_matches v830_health v827_context_limits_config v354_ui_links_pins" \
  bash tests/battery.sh

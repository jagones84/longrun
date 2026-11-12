#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
# 2026-11-13 RSI-V: a repeated verify must beat a fair coin at `promotion_alpha`; the
# bound is stamped on the archived proposal, single-run cases are named, never faked.
# v788/v789 are the case-table gate it extends, v598 the streak/threshold release,
# v205 the sealed held-out gate, v790/v823/v416 the promotion lifecycle.
set -u
cd /home/jagones/Repositories/longrun || exit 1
LONGRUN_BATTERY_TESTS="v965_promotion_bound v788_evolve_case_gate v789_evolve_gate_measures v598_thresholded_release v205_heldout_gate v790_evolve_retire_and_failures v823_skill_supersede v416_autoskill_created" \
  bash tests/battery.sh

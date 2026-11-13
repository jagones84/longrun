#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
# 2026-11-13 AA: a harness version is published only if it still matches the reviewed one
# (selfevolve verify stamps a digest; promote refuses a mismatch). v971 is the new pin; the
# other names all exercise the verify->promote path that must stay green; v354 pins the
# README badge bumped by the new test.
set -u
cd /home/jagones/Repositories/longrun || exit 1
LONGRUN_BATTERY_TESTS="v971_verify_promote_consistency v965_promotion_bound v789_evolve_gate_measures v788_evolve_case_gate v717_archived_skill_text v598_thresholded_release v416_autoskill_created v280_bestofn_selfevolve v354_ui_links_pins" \
  bash tests/battery.sh

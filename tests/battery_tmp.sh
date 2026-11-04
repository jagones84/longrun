#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v796_reviewer_role v727_selfevolve_semantic_abstraction v789_evolve_gate_measures v790_evolve_retire_and_failures v354_ui_links_pins v792_inject_identical_cap v794_memory_workspace_scope"
exec bash tests/battery.sh

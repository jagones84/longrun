#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v794_memory_workspace_scope v204_memory_governance v207_abuse_hard v212_abuse_hard2 v317_memory_true_delete v628_memory_supersession v662_one_address_one_store v659_matrix_layer_fixes v272_context_accounting v485_compaction_transcript v458_compaction_model_vision v792_inject_identical_cap v791_invalid_reply_cap_config v769_harness_trace_truthfulness v793_dsml_parameter_bleed"
exec bash tests/battery.sh

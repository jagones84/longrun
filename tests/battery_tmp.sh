#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v813_bench_tokens v814_ungraded_policy v815_single_token_truth v816_failure_cause v817_bestofn_variation v818_memory_use_signal v354_ui_links_pins v664_run_manifest v571_bestofn_scorer v280_bestofn_selfevolve v267_context_items v794_memory_workspace_scope v272_context_accounting v487_compaction_policy"
exec bash tests/battery.sh

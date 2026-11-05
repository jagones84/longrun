#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v819_memory_kinds v820_guardrail_firings v813_bench_tokens v814_ungraded_policy v815_single_token_truth v816_failure_cause v817_bestofn_variation v818_memory_use_signal v354_ui_links_pins v446_improvement v668_chat_taint v204_memory_governance v794_memory_workspace_scope v618_permit_shell_bypass v595_trust_profiles"
exec bash tests/battery.sh

#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v793_dsml_parameter_bleed v782_dsml_multi_invoke v792_inject_identical_cap v791_invalid_reply_cap_config v774_invalid_reply_recovery v769_harness_trace_truthfulness v748_todo_partial_update v787_verifier_wired_and_bounded"
exec bash tests/battery.sh

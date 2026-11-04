#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v792_inject_identical_cap v791_invalid_reply_cap_config v774_invalid_reply_recovery v750_verify_gate v783_readback_gap_once v769_harness_trace_truthfulness v701_harness_repeats v266_task_guidance v332_harness_start_marker v485_compaction_transcript v613_session_tools"
exec bash tests/battery.sh

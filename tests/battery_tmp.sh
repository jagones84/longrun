#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v826_harness_wire_label v792_inject_identical_cap v485_compaction_transcript v462_jag465_realtime_vision_links v616_permit_gate_and_secrets v183_chat_core v736_tool_call_repair v443_live_ui v354_ui_links_pins v774_invalid_reply_recovery v783_readback_gap_once v795_steer_durable_visible v456_webui_session_ui_state v458_compaction_model_vision v769_harness_trace_truthfulness v350_session_inspect v693_harness_chat_diagnostics v701_harness_repeats v798_probe_repeats"
exec bash tests/battery.sh

#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v827_context_limits_config v828_edit_integrity v491_settings_forms v742_arg_name_repair v347_observation_payload v596_post_edit_syntax_gate v732_batch_observation_integrity v489_description_claims v354_ui_links_pins v826_harness_wire_label v183_chat_core v656_miner_quality_reinjection v462_jag465_realtime_vision_links v736_tool_call_repair v350_session_inspect"
exec bash tests/battery.sh

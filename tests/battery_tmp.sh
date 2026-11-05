#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v827_context_limits_config v354_ui_links_pins v489_description_claims v732_batch_observation_integrity v656_miner_quality_reinjection v344_plan_only v696_harness_whole_run v413_resilience v826_harness_wire_label v462_jag465_realtime_vision_links v792_inject_identical_cap v183_chat_core v350_session_inspect v485_compaction_transcript v616_permit_gate_and_secrets v469_untitled_autoname"
exec bash tests/battery.sh

#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v774_invalid_reply_recovery v736_tool_call_repair v751_argkv_tool_dialect v369_dsml_tool_calls v764_answer_discipline v304_json_artifact v303_job_delegation v769_harness_trace_truthfulness v773_live_choices_and_watcher_and_queue_edit v772_generate_surfaces v542_autoidx_visibility v540_automate_scope v534_longrun_agent_veo v768_goal_verify_and_delegation v510_goal_completion v705_goal_persistence v354_ui_links_pins"
exec bash tests/battery.sh

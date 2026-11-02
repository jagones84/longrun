#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v770_model_blank_failover v769_harness_trace_truthfulness v768_goal_verify_and_delegation v767_agent_workspace_subtree v537_exclusive_tool_objects v740_exclusive_delta_only v354_ui_links_pins v253_registry_catalog v679_automation_ledger v733_human_ask_tool v266_task_guidance v272_context_accounting v557_prompt_security v668_chat_taint v672_subagent_tool_scope v419_api_parity v350_session_inspect v674_send_idempotency v595_trust_profiles v491_settings_forms"
exec bash tests/battery.sh

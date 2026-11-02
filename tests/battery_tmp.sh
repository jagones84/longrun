#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v767_agent_workspace_subtree v537_exclusive_tool_objects v740_exclusive_delta_only v354_ui_links_pins v253_registry_catalog v679_automation_ledger v733_human_ask_tool v668_chat_taint v672_subagent_tool_scope v567_consumable_approval v419_api_parity"
exec bash tests/battery.sh

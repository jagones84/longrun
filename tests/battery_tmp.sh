#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v768_goal_verify_and_delegation v177_session_delete_cascade v705_goal_persistence v510_goal_completion v460_jag463_composer_tools v584_closure_check v592_finish_gate v266_task_guidance v557_prompt_security v354_ui_links_pins v767_agent_workspace_subtree v253_registry_catalog"
exec bash tests/battery.sh

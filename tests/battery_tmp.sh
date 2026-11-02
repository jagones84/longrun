#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v768_goal_verify_and_delegation v584_closure_check v592_finish_gate v266_task_guidance v269_id_first_todos v278_supersede_guard v557_prompt_security v744_artifact_verification_policy v271_prompt_alignment v273_cache_and_cleanup v767_agent_workspace_subtree v253_registry_catalog v354_ui_links_pins"
exec bash tests/battery.sh

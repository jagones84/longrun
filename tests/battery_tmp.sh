#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v773_live_choices_and_watcher_and_queue_edit v772_generate_surfaces v542_autoidx_visibility v540_automate_scope v534_longrun_agent_veo v679_automation_ledger v678_teamorg_scope v768_goal_verify_and_delegation v177_session_delete_cascade v764_answer_discipline v354_ui_links_pins v266_task_guidance v584_closure_check v592_finish_gate"
exec bash tests/battery.sh

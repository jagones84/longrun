#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v844_rules_audit v845_third_correction v846_approval_fatigue v847_tool_footprint v848_skill_discovery v849_harness_ablation v183_chat_core v361_rules_cost_polish v593_run_bound_approval v565_taint_standing_approval v198_skills_tools_awareness v712_skill_loop_closed v354_ui_links_pins"
exec bash tests/battery.sh

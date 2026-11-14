#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
# 2026-11-14 (round 2, diversified bug hunt): v983 action-case policy bypass, v984 shell-variable
# workspace boundary, v985 stale session Stop killing the next run, v986 dead per-tool frequency
# override. v556 pins the frequency guard, v941/v945 the alias+shell boundary, v264 arg repair,
# v968 the subtool warning, v767 the workspace subtree, v983-v986 are new; the run-loop pair
# (v464/v982) and the README badge (v354) close the gate.
set -u
cd /home/jagones/Repositories/longrun || exit 1
LONGRUN_BATTERY_TESTS="v983_action_case_gate v984_shell_var_boundary v985_run_clears_stale_stop v986_loop_freq_override v556_tool_frequency v941_gate_alias_and_env_prefix v945_shell_workspace_boundary v264_normalize_throttle v968_subtool_action_not_ignored v767_agent_workspace_subtree v464_paperclip_run_outcome v982_run_acceptance v977_finish_summary_verbatim v354_ui_links_pins" \
  bash tests/battery.sh

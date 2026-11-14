#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
# 2026-11-14 (round 5, whole-system bug hunt, one chapter each):
#   v989 read-tool workspace boundary (grep.search/glob.list were auto outside the box)
#   v990 parse_status last declaration (a quoted DONE beat the real BLOCKED)
#   v991 query_events bad time filter (sqlite placeholder mismatch -> dead connection)
#   v992 chunk window guard (chunk_lines=0 hung the indexer)
#   v993 tool args must be an object (a string crashed POST /api/tools/call)
# Neighbours: v337 (worker outcome), v262/v418 (event recovery + rewind), v945/v767/v984
# (workspace boundary family), v801/v802/v618/v808 (policy + blocked reason), v183/v419/
# v510/v567/v736 (the gated_call door), v354 (badge).
set -u
cd /home/jagones/Repositories/longrun || exit 1
LONGRUN_BATTERY_TESTS="v989_read_tool_workspace_boundary v990_parse_status_last_declaration v991_query_events_bad_time_filter v992_chunk_window_guard v993_tool_args_must_be_object v337_worker_outcome v262_recovery v418_rewind_restore v945_shell_workspace_boundary v767_agent_workspace_subtree v984_shell_var_boundary v801_blocked_reason v802_git_push_allowed v618_permit_shell_bypass v808_permissions_restore v183_chat_core v419_api_parity v510_tool_discovery v567_consumable_approval v736_tool_call_repair v354_ui_links_pins" \
  bash tests/battery.sh

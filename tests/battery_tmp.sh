#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v835_orphan_turn_abort v834_grep_workspace_path v442_abort_stop v753_stop_kills_work v222_delete_running v183_chat_core v354_ui_links_pins"
exec bash tests/battery.sh

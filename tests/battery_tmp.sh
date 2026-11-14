#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
# 2026-11-14 v1000: the reply parser accepts the bare-`action` tool dialect (session b7329cccf94c).
# Live evidence: glm-5.3-flash emitted `<tool_call>action` + <arg_key>tool</arg_key><arg_value>fs.read</arg_value>
# + <arg_key>args</arg_key>… with NO `action` pair; _argkv_action returned None, every call was
# rejected ("Your reply could not be executed", ~25 retries) and the turn burned its budget with
# 5 of 8 steps open. A `tool` pair IS the call.
# The other names are the dependency oracle: the reply/markup contract (v904), the invalid-reply
# recovery strategy switch (v774), its caps (v791, v792), the chat loop (v183), the budget fix
# from the same incident (v999) and the badge pin (v354).
set -u
cd /home/jagones/Repositories/longrun || exit 1
LONGRUN_BATTERY_TESTS="v751_argkv_tool_dialect v904_reply_not_markup v774_invalid_reply_recovery v791_invalid_reply_cap_config v792_inject_identical_cap v183_chat_core v999_todo_round_budget v354_ui_links_pins" \
  bash tests/battery.sh

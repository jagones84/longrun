#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
# 2026-11-14 v999: a round the harness REJECTED is not charged to the work budget (JAG-402).
# Live evidence: session b7329cccf94c stopped at `plan.stopped budget open=5/8 rounds=10` after
# 253.9s, and 4 of those 10 rounds were "your final answer was REJECTED" — JAG-402's forcing,
# which already has its own budget (_close_todo_max). The work budget paid for it twice.
# The other names are the dependency oracle: the chat loop (v183's JAG-402 scenario I), the
# open-todos gate (v449, v459's JAG-462 sweep), the goal loop (v510), the turn-end card (v733),
# the injection contract (v868), the last lot (v998) and the badge pin (v354).
set -u
cd /home/jagones/Repositories/longrun || exit 1
LONGRUN_BATTERY_TESTS="v999_todo_round_budget v183_chat_core v449_open_todos_gate v459_jag462_sweep v510_goal_completion v733_human_ask_tool v868_one_kind_per_gate v975_selfevolve_e2e v998_memory_anchors v354_ui_links_pins" \
  bash tests/battery.sh

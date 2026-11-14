#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
# 2026-11-14 v996 (CO-1): the always-injected memory INDEX respects the session's workspace.
# CoReMem (arXiv 2611.17316) calls a memory of the wrong repository a "misplaced memory": it costs
# steps. Longrun wrote `workspace=` and filtered the turn RETRIEVAL, but `prompt._provider_memory`
# accepted a workspace and ignored it, so the newest lessons of every OTHER project rode this
# project's prompt (live: 2 of 4 injected lessons were foreign). `governed_query` now takes the
# workspace; the turn and the Context panel render the same scoped block.
# The other names are the dependency oracle: every memory consumer (prompt buckets, governance,
# supersession, the meter, the taint gate, the Matrix seam) and the badge pin.
set -u
cd /home/jagones/Repositories/longrun || exit 1
LONGRUN_BATTERY_TESTS="v996_memory_workspace_scope v929_memory_in_user_turn v819_memory_kinds v853_prompt_memory_dedupe_budget v972_memory_hygiene v204_memory_governance v628_memory_supersession v662_one_address_one_store v317_memory_true_delete v446_improvement v668_chat_taint v503_matrix_deep_package_seams v659_matrix_layer_fixes v354_ui_links_pins" \
  bash tests/battery.sh

#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
# 2026-11-14 v998 (CO-3): a finished turn leaves WHERE/VERIFY anchors for the next one.
# CoReMem (arXiv 2611.17316 §3.1) values a memory by what its REMOVAL costs the next task; what pays
# is the location and the check command, not the narrative. Longrun stored the raw material (one tool
# card per call: path, command, exit code) and extracted anchors for compaction only. `memory/anchors`
# now writes ONE bounded `repo.anchor` note per turn that touched files, with no model call, injected
# in its own bucket and subject to the ordinary workspace/dedupe/budget governance.
# The other names are the dependency oracle: the end-of-turn pass (v446/v799 call it directly), the
# memory governance/hygiene of the new kind, CO-1's scoping, and the badge pin.
set -u
cd /home/jagones/Repositories/longrun || exit 1
LONGRUN_BATTERY_TESTS="v998_memory_anchors v446_improvement v799_reflect_evidence v972_memory_hygiene v996_memory_workspace_scope v929_memory_in_user_turn v819_memory_kinds v853_prompt_memory_dedupe_budget v354_ui_links_pins" \
  bash tests/battery.sh

#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
# 2026-11-14 v997 (CO-2): the memory store can be REMOVED for one arm of a run.
# CoReMem (arXiv 2611.17316) values a memory by what the next task saves with it and without it.
# `memory.py` built its own folder while every other store subdirectory was overridable, so the
# ablation instrument (skills/rules/hooks) could not remove memory. `paths.MEMORY_DIR` +
# `LONGRUN_MEMORY_DIR` is now the ONE owner; `benchmarks/ablation.py` gains a `memory` layer.
# The other names are the dependency oracle: the ablation instrument itself (v849 iterates every
# layer), the memory consumers CO-1 scoped, the improvement ledger that names the written file, and
# the badge pin.
set -u
cd /home/jagones/Repositories/longrun || exit 1
LONGRUN_BATTERY_TESTS="v997_memory_ablation v849_harness_ablation v996_memory_workspace_scope v929_memory_in_user_turn v819_memory_kinds v972_memory_hygiene v354_ui_links_pins" \
  bash tests/battery.sh

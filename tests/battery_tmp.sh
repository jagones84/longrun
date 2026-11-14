#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
# 2026-11-14 (round 4, bug-hunt `context` axis): v988 pins "a carried summary is
# byte-identical — no anchors mined from [harness] scaffolding". v676 is the anchors
# contract, v458/v931 the compaction paths, v827 the context budgets, v854/v856 the
# meter, v684 the JAG-461 noise rule; v987 (the deny list, same session) and v354
# (the badge) close the gate.
set -u
cd /home/jagones/Repositories/longrun || exit 1
LONGRUN_BATTERY_TESTS="v988_carried_summary_no_scaffold_anchors v676_compaction_anchors v458_compaction_model_vision v931_wire_history_reproducible v827_context_limits_config v854_context_meter_no_rerank v856_context_items_single_render v987_deny_root_delete_and_proc_environ v354_ui_links_pins" \
  bash tests/battery.sh

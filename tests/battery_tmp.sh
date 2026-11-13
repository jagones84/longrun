#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
# 2026-11-14 v973: the two file stores the harness writes got a bound AND a caller —
# `data/checkpoints` (the index cap now takes the payload with the entry; `prune()` also
# removes unreachable ORPHAN payloads, 533 MB measured) and `data/offload` (one file per
# oversized observation, 158 folders / 32 MB, never pruned). The other names are the
# dependency oracle: the checkpoint lifecycle, the session-delete cascade that now also
# purges the offload folder, the config owner, the v972 memory bound, and the badge pin.
set -u
cd /home/jagones/Repositories/longrun || exit 1
LONGRUN_BATTERY_TESTS="v973_store_bounds v972_memory_hygiene v318_ckpt_approvals_delete v424_checkpoint_route v499_matrix_checkpoints_and_git v177_session_delete_cascade v314_cascade_delete v315_session_delete_final v827_context_limits_config v354_ui_links_pins" \
  bash tests/battery.sh

#!/usr/bin/env bash
# targeted gate: round 75 — the optimizer is shown the LIVE policy
set -u
cd /home/jagones/Repositories/MyRepos/longrun || exit 1
LONGRUN_BATTERY_TESTS="v1140_optimizer_sees_live_policy v1011_local_optimizer v1013_optimizer_delta v1015_registry_adoption v1017_self_evolution_loop v1074_evolution_history_pruner v1091_repair_drafts v805_permissions_page v1008_registry_contract_truth v354_ui_links_pins" \
  bash tests/battery.sh

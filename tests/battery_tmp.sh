#!/usr/bin/env bash
# targeted gate: round 76 — the optimizer names why its model call failed
set -u
cd /home/jagones/Repositories/MyRepos/longrun || exit 1
LONGRUN_BATTERY_TESTS="v1141_optimizer_call_failure v1140_optimizer_sees_live_policy v1011_local_optimizer v1013_optimizer_delta v1015_registry_adoption v1017_self_evolution_loop v1074_evolution_history_pruner v354_ui_links_pins" \
  bash tests/battery.sh

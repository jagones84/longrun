#!/usr/bin/env bash
# targeted gate: round 77 — the optimizer has its own live model route
set -u
cd /home/jagones/Repositories/MyRepos/longrun || exit 1
LONGRUN_BATTERY_TESTS="v1142_optimizer_live_route v1141_optimizer_call_failure v1140_optimizer_sees_live_policy v1011_local_optimizer v1013_optimizer_delta v1015_registry_adoption v1017_self_evolution_loop v1074_evolution_history_pruner v796_reviewer_role v354_ui_links_pins" \
  bash tests/battery.sh

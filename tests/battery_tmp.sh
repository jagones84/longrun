#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v853_prompt_memory_dedupe_budget v854_context_meter_no_rerank v270_context_occupancy v267_context_items v273_cache_and_cleanup v285_orbit_beta v288_decisions v256_robustness"
exec bash tests/battery.sh

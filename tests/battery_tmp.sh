#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v855_registry_config_parse_memo v856_context_items_single_render v853_prompt_memory_dedupe_budget v854_context_meter_no_rerank v847_tool_footprint v836_self_tools_payload v843_step_action_gate v198_skills_tools_awareness v270_context_occupancy v267_context_items v273_cache_and_cleanup v305_output_budget v337_worker_outcome v414_self_diag v256_robustness v285_orbit_beta v288_decisions v453_round4 v850_ui_audit_surfaces v631_rail_toolbar"
exec bash tests/battery.sh

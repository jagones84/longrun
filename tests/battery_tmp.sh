#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
# v923: the failover cost accounting (DR-R) + the three items closed before it in this session.
set -u
TESTS="v923_failover_cost_accounted v921_config_copy_atomic_save v919_gate_cost_basis v909_approval_trim_keeps_pending v558_cost_attempts v470_agent_model_retry v471_run_session_model_truth v217_provider_failfast v447_router_failed_model v561_run_token_budget v563_subagent_run_budget v666_run_token_budget_config v664_run_manifest v770_model_blank_failover v789_evolve_gate_measures v790_evolve_retire_and_failures v555_improve_evolve_gate v205_heldout_gate v645_skill_proposal_apply v714_harness_skill_admission v722_selfevolve_edge_errors v727_selfevolve_semantic_abstraction v578_miner_junk_filter v656_miner_quality_reinjection v565_taint_standing_approval v567_consumable_approval v593_run_bound_approval v618_permit_shell_bypass v668_chat_taint v846_approval_fatigue v806_permissions_split v318_ckpt_approvals_delete v195_hard v386_shell_cwd v419_api_parity v458_compaction_model_vision v459_jag462_sweep v673_quota_cooldown v796_reviewer_role v251_settings_wire v488_config_editor v506_settings_autosave_dirty v588_cli_route_parity v354_ui_links_pins"
cd /home/jagones/Repositories/longrun || exit 1
fail=0
for t in $TESTS; do
  out=$(python3 "tests/acceptance/$t.py" 2>&1) || { echo "FAIL $t"; echo "$out" | tail -8; fail=1; continue; }
  echo "ok   $t  $(echo "$out" | tail -1)"
done
set -- $TESTS
[ "$fail" = 0 ] && echo "=== battery: $# GREEN ===" || echo "=== battery: RED ==="
exit "$fail"

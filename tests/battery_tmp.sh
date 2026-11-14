#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
# 2026-11-14 H1-H6/A1: the six harness-side findings of reports/2026-11-14_agent-session-issues.md
# -- full finish summary, nested-args merge, config-sized run observation + offload,
# coalesced reasoning deltas, failed calls in the closure record, per-run acceptance.
# v464/v465/v466/v471/v472/v976 pin the run loop, its stream and its session transcript;
# v349 the loop history; v828/v489/v732/v453 the offload owner; v968 the arg-shape gate;
# v827 the context limits; v354 the README badge; the UI guard proves the shell did not move.
set -u
cd /home/jagones/Repositories/longrun || exit 1
LONGRUN_BATTERY_TESTS="v977_finish_summary_verbatim v978_nested_args_merged v979_run_observation_budget v980_run_think_coalesced v981_run_failures_in_finish v982_run_acceptance v464_paperclip_run_outcome v465_paperclip_stream_route v466_paperclip_rest_bridge v471_run_session_model_truth v472_run_visibility_panel v976_agent_run_transcripts_session v349_agent_loop_history v231_body_and_ids v828_edit_integrity v489_description_claims v732_batch_observation_integrity v453_round4 v968_subtool_action_not_ignored v827_context_limits_config v536_ui_edit_parity v354_ui_links_pins" \
  bash tests/battery.sh

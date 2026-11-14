#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
# 2026-11-14 v994 (OCM): a mined candidate now carries the OUTCOME and the PURPOSE of the runs
# it came from. `record()` stored {tools, ts} only, so "91 candidates, all one shape" was all the
# miner could say; `history_rows()` promised "outcome attribution" it could not deliver, and
# `draft(purpose=)` wrote a purpose nothing filled. A pattern whose known runs ALL failed is now
# refused before a draft exists; a row with no outcome is UNKNOWN and is never read as a success,
# so the 500 rows already stored neither mint a false success nor get blocked retroactively.
# The other names are the dependency oracle: every test that pins mining, drafting, verifying,
# promoting, retiring or superseding, plus the badge pin and the UI guard.
set -u
cd /home/jagones/Repositories/longrun || exit 1
LONGRUN_BATTERY_TESTS="v994_outcome_conditioned_mining v975_selfevolve_e2e v280_bestofn_selfevolve v416_autoskill_created v446_improvement v555_improve_evolve_gate v598_thresholded_release v645_skill_proposal_apply v662_one_address_one_store v710_selfevolve_visibility v711_draft_sweep_owner v712_skill_loop_closed v713_draft_synth_owner v717_archived_skill_text v721_evolve_forges_matrix v722_selfevolve_edge_errors v723_matrix_bundle_end_to_end v727_selfevolve_semantic_abstraction v788_evolve_case_gate v789_evolve_gate_measures v790_evolve_retire_and_failures v823_skill_supersede v919_gate_cost_basis v965_promotion_bound v966_skill_retire v971_verify_promote_consistency v972_memory_hygiene v205_heldout_gate v827_context_limits_config v354_ui_links_pins" \
  bash tests/battery.sh

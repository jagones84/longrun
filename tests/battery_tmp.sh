#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
# 2026-11-14 v975/v976: self-evolution validated END TO END on one artefact. Measured live:
# 500 recorded runs -> 91 mined candidates -> 123 drafts -> 0 installed skills, because the
# sealed held-out judge suite was never installed and `promote` therefore refused every
# candidate. `heldout.install()` writes and pins that judge (8 checks, can refuse), `pin()`
# keeps the installed command, `promote`/`retire` now write the improvement-ledger rows they
# never did, and the skill arm gets the per-pass bound the code arm always had.
# The other names are the dependency oracle: every pin that asserts promote/retire/supersede
# behaviour, the sealed gate itself, the memory bound that feeds the loop, and the badge.
set -u
cd /home/jagones/Repositories/longrun || exit 1
LONGRUN_BATTERY_TESTS="v975_selfevolve_e2e v205_heldout_gate v280_bestofn_selfevolve v416_autoskill_created v446_improvement v555_improve_evolve_gate v598_thresholded_release v645_skill_proposal_apply v662_one_address_one_store v710_selfevolve_visibility v711_draft_sweep_owner v712_skill_loop_closed v713_draft_synth_owner v717_archived_skill_text v721_evolve_forges_matrix v722_selfevolve_edge_errors v723_matrix_bundle_end_to_end v727_selfevolve_semantic_abstraction v788_evolve_case_gate v789_evolve_gate_measures v790_evolve_retire_and_failures v823_skill_supersede v919_gate_cost_basis v965_promotion_bound v971_verify_promote_consistency v972_memory_hygiene v827_context_limits_config v354_ui_links_pins" \
  bash tests/battery.sh

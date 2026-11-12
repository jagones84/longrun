#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
# 2026-11-13 HD-3: a zero-tool reply that CLAIMS a change earns one round (the action
# gate). v969 is the new pin; v868 is the gate-kind registry it joins; v764 is the
# evidence gate it complements; v869/v750/v731/v776 are the read-back/gate neighbours;
# v354 pins the README badge bumped by the new test.
set -u
cd /home/jagones/Repositories/longrun || exit 1
LONGRUN_BATTERY_TESTS="v969_action_claim_gate v868_one_kind_per_gate v764_answer_discipline v869_gate_dedupe v750_verify_gate v731_deliverable_readback v776_readback_turn_attribution v354_ui_links_pins" \
  bash tests/battery.sh

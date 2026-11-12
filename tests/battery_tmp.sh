#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
# 2026-11-13 RSI-U: the improvement cycle records its own token bill (propose from the
# router's usage, probe from each run record, "not measured" when a record has no number).
# v687/v692 are the cycle's own pins, v684/v691/v694 the editor contract it reads.
set -u
cd /home/jagones/Repositories/longrun || exit 1
LONGRUN_BATTERY_TESTS="v963_cycle_tax v687_harness_cycle v692_harness_cycle_integrity v684_harness_editors v691_harness_candidate_ownership v694_harness_editor_reuse" \
  bash tests/battery.sh

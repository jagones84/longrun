#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v403_ui_fixes v764_answer_discipline v731_deliverable_readback"
exec bash tests/battery.sh

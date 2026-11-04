#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v800_session_scan v287_routines_budget v620_id_counter_retract v799_reflect_evidence v798_probe_repeats v797_improvement_stamp v796_reviewer_role v446_improvement v507_namespaced_subtools v354_ui_links_pins"
exec bash tests/battery.sh

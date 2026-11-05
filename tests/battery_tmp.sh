#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v801_blocked_reason v507_namespaced_subtools v590_interrupt_classify v350_session_inspect v791_invalid_reply_cap_config v792_inject_identical_cap v800_session_scan v799_reflect_evidence v354_ui_links_pins"
exec bash tests/battery.sh

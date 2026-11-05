#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v802_git_push_allowed v801_blocked_reason v420_decision_hooks v618_permit_shell_bypass v507_namespaced_subtools v590_interrupt_classify v641_settings_ia v354_ui_links_pins"
exec bash tests/battery.sh

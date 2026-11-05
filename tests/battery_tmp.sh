#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v806_permissions_split v805_permissions_page v804_shell_background v803_hitl_batch v733_human_ask_tool v530_shared_terminal v595_trust_profiles v618_permit_shell_bypass v801_blocked_reason v420_decision_hooks v641_settings_ia v354_ui_links_pins v507_namespaced_subtools"
exec bash tests/battery.sh

#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v775_slash_commands v279_composer v863_per_session_status_and_commands v354_ui_links_pins v851_ui_a11y_gate v504_webui_script_balance v238_context_robustness v848_skill_discovery"
exec bash tests/battery.sh

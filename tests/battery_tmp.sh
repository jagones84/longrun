#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v878_rail_follows_backend_naming v863_per_session_status_and_commands v862_stop_kills_naming v469_untitled_autoname v851_ui_a11y_gate v504_webui_script_balance v354_ui_links_pins"
exec bash tests/battery.sh

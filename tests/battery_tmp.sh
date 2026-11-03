#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v777_landscape_chat v761_mobile_drawers v368_panel_resize v758_rail_grammar v778_session_ids_and_sparkle_cache v354_ui_links_pins"
exec bash tests/battery.sh

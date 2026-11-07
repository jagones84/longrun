#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v865_tool_example_contract v866_fs_link_resolution v364_queue_theme_links_ctx v510_tool_discovery v354_ui_links_pins v851_ui_a11y_gate v414_self_diag v836_self_tools_payload"
exec bash tests/battery.sh

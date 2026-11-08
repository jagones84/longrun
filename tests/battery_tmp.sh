#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v881_control_deck_layout v880_skill_chip_and_jump_arrow v879_one_control_per_rail_job v878_rail_follows_backend_naming v851_ui_a11y_gate v776_readback_turn_attribution v504_webui_script_balance v354_ui_links_pins"
exec bash tests/battery.sh

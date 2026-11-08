#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v879_one_control_per_rail_job v878_rail_follows_backend_naming v426_composer_tree v429_new_session_and_cot v435_free_threads v511_ui_cot_slash_camera v428_reveal_active_session v851_ui_a11y_gate v504_webui_script_balance v354_ui_links_pins"
exec bash tests/battery.sh

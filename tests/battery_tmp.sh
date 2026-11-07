#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v772_generate_surfaces v540_automate_scope v534_longrun_agent_veo v778_session_ids_and_sparkle_cache v436_mobile_theme_goal v636_rail_fields v634_rail_density v851_ui_a11y_gate v504_webui_script_balance v702_composer_stop_send"
exec bash tests/battery.sh

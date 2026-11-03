#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v778_session_ids_and_sparkle_cache v777_landscape_chat v772_generate_surfaces v534_longrun_agent_veo v354_ui_links_pins v761_mobile_drawers"
exec bash tests/battery.sh

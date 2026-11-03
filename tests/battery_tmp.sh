#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v778_session_ids_and_sparkle_cache v340_team_scope v772_generate_surfaces v624_operator_round2 v285_orbit_beta v617_deck_rail v289_job_ops v354_ui_links_pins v777_landscape_chat"
exec bash tests/battery.sh

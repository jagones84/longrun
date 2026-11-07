#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v867_rail_sections_and_modes v284_ui_polish v361_rules_cost_polish v364_queue_theme_links_ctx v637_composer_density v702_composer_stop_send v762_ui_chrome v763_ui_icons v779_editor_rail v780_rail_states v851_ui_a11y_gate v354_ui_links_pins v426_composer_tree v278_supersede_guard v428_reveal_active_session v497_inspector_bulk_toggle v368_panel_resize v504_webui_script_balance"
exec bash tests/battery.sh

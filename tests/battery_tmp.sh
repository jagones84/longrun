#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v825_models_panel_uniform v407_models_panel v824_rerank_stage v491_settings_forms v654_models_apply_modes v655_single_writer_test_chips v609_job_bridge_and_research_model v641_settings_ia v643_harness_cards v652_ui_store_sync v401_embedding_costs v354_ui_links_pins v284_ui_polish v763_ui_icons v779_editor_rail v780_rail_states v505_editor_tree_settings v309_model_sync v281_terminal_models v343_team_models v419_api_parity"
exec bash tests/battery.sh

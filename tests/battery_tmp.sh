#!/usr/bin/env bash
# targeted gate: two-step document approval + operator-only policy writes
set -u
cd /home/jagones/Repositories/longrun || exit 1
LONGRUN_BATTERY_TESTS="v1052_doc_plan_spec v1051_slash_catalog v1053_slash_menu_ui v785_cli_command_cases v587_cli_parity v588_cli_route_parity v312_cli_parity v506_settings_autosave_dirty v825_models_panel_uniform v805_permissions_page v808_permissions_restore v1008_registry_contract_truth v198_skills_tools_awareness v415_baseline_tools v847_tool_footprint v949_tool_access_truth v903_detached_dispatch v934_composer_session_drafts" \
  bash tests/battery.sh

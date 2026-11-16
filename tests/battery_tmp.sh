#!/usr/bin/env bash
# targeted gate: .longrun ignored + the CLI `docs` twin
set -u
cd /home/jagones/Repositories/longrun || exit 1
LONGRUN_BATTERY_TESTS="v1052_doc_plan_spec v1053_slash_menu_ui v587_cli_parity v588_cli_route_parity v312_cli_parity v785_cli_command_cases v934_composer_session_drafts" \
  bash tests/battery.sh

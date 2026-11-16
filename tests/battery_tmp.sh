#!/usr/bin/env bash
# targeted gate for the /reset · /unlock · removable bar · attachment preview round
set -u
cd /home/jagones/Repositories/longrun || exit 1
LONGRUN_BATTERY_TESTS="v1051_slash_catalog v1052_doc_plan_spec v1053_slash_menu_ui v1020_user_commands v775_slash_commands" \
  bash tests/battery.sh

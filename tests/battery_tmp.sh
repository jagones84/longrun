#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v264_normalize_throttle v511_ui_cot_slash_camera v274_chat_stream v429_new_session_and_cot"
exec bash tests/battery.sh

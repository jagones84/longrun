#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v832_honesty_contract v831_lhb v557_prompt_security v744_artifact_verification_policy v271_prompt_alignment v272_context_accounting v354_ui_links_pins v183_chat_core"
exec bash tests/battery.sh

#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v781_tool_schema_clarity v742_arg_name_repair v736_tool_call_repair v510_tool_discovery v527_prices_refresh v740_exclusive_delta_only v749_fs_edit_aliases v507_namespaced_subtools"
exec bash tests/battery.sh

#!/usr/bin/env bash
# TARGETED battery — the tests of the fix in flight. OVERWRITE this file on every
# fix: the list below replaces nothing else, it only narrows the gate. The full
# suite (tests/battery.sh) runs when the operator asks or when the last full run
# is overdue; the test itself is already auto-discovered by `tests/acceptance/v*.py`,
# so "adding it to the total battery" means nothing more than keeping the file here.
#
# Why a separate launcher: the operator's rule (2026-10-31) is that a fix must be
# proven FAST and on the tests that can actually break because of it, not by paying
# the whole suite every time.
#
# Usage: bash tests/battery_tmp.sh
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"

# ---- fix under test (overwrite this line) --------------------------------
TESTS="v755_tb_adapter v354_ui_links_pins"
# --------------------------------------------------------------------------

LONGRUN_BATTERY_TESTS="$TESTS" exec bash "$HERE/battery.sh"

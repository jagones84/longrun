#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
# 2026-11-14 v995 (HD-2): a turn's trace TREE and the FIRST step that went wrong.
# `util/tracing` keeps a flat span list and `_render_transcript` a flat ordered log, so a failed
# turn was diagnosed by reading and guessing. The stores already held everything: every tool card has
# `ok`/`error`/`exit_code`/`node`/`after`, and the plan's steps are graph nodes. `util/runtree`
# groups them STAGE (plan step) → STEP (tool call) and names the onset with recovery + retries;
# `GET /api/sessions/<id>/trace-tree` and `forge.py sessions tree ID` expose it. `error_class`
# is now public in selfevolve because runtree must not own a second normalizer.
# The other names are the dependency oracle: the CLI parity pins (a new verb + route), the
# selfevolve suites (the renamed public symbol), and the badge pin.
set -u
cd /home/jagones/Repositories/longrun || exit 1
LONGRUN_BATTERY_TESTS="v995_trace_tree_onset v994_outcome_conditioned_mining v975_selfevolve_e2e v790_evolve_retire_and_failures v687_harness_cycle v588_cli_route_parity v587_cli_parity v312_cli_parity v785_cli_command_cases v354_ui_links_pins" \
  bash tests/battery.sh

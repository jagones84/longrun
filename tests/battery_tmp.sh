#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
# 2026-11-14 v976: a session-scoped GET /api/agent/run transcripts into ITS session
# (goal = user turn, outcome = reply, one model); v465/v466/v472/v349/v231 pin the
# streaming run, the Paperclip bridge and the agent-loop history this reuses,
# v354 pins the README badge count, the UI guard proves the shell did not move.
set -u
cd /home/jagones/Repositories/longrun || exit 1
LONGRUN_BATTERY_TESTS="v976_agent_run_transcripts_session v465_paperclip_stream_route v466_paperclip_rest_bridge v472_run_visibility_panel v349_agent_loop_history v231_body_and_ids v354_ui_links_pins" \
  bash tests/battery.sh

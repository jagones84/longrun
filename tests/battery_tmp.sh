#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
# 2026-11-14 (round 3, policy findings from the bug-hunt `policy` session): v987 pins the
# broadened hard-deny list (every recursive+force root delete, /proc/*/environ reads,
# mkfs.<fs>, dd writing a block device). The deny list is the only gate that survives
# approvals.mode=full, so its neighbours are the gate: v802 (git push vs shell deny),
# v618 (shell bypass ingredients), v801 (blocked reason), v805/v808 (permissions page
# + restore), v941/v945 (alias + shell boundary), v984 (variable path). v354 is the badge.
set -u
cd /home/jagones/Repositories/longrun || exit 1
LONGRUN_BATTERY_TESTS="v987_deny_root_delete_and_proc_environ v802_git_push_allowed v618_permit_shell_bypass v801_blocked_reason v805_permissions_page v808_permissions_restore v941_gate_alias_and_env_prefix v945_shell_workspace_boundary v984_shell_var_boundary v983_action_case_gate v806_permissions_split v354_ui_links_pins" \
  bash tests/battery.sh

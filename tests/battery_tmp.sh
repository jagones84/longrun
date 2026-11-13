#!/usr/bin/env bash
# battery_tmp.sh — the fix in flight. Overwritten every round; tests/battery.sh is the gate.
# 2026-11-14 v974: a tool POLICY that names no provider is reported, never silently dropped.
# `catalog()` skips a row it cannot resolve, so the live config held 28 dead capabilities —
# 26 `PMCP__gateway.*` duplicate spellings, `python_sandbox__run_python_code` (named by a
# Global rule that every session loads) and `sequential-thinking__sequentialthinking` — with
# no signal at all. `registry.orphan_policies()` + `diag.namespaces()["orphans"]` is the
# report; the 27 overlay keys are removed. The other names are the dependency oracle:
# the registry/self.info surfaces that must keep working, the config owner and the badge pin.
set -u
cd /home/jagones/Repositories/longrun || exit 1
LONGRUN_BATTERY_TESTS="v974_tool_policy_orphans v718_self_info_identity v414_self_diag v510_tool_discovery v198_skills_tools_awareness v855_registry_config_parse_memo v973_store_bounds v972_memory_hygiene v827_context_limits_config v354_ui_links_pins" \
  bash tests/battery.sh

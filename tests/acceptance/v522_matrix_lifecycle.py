#!/usr/bin/env python3
"""v522 — Matrix artifact lifecycle, complete hot uninstall, unified approvals.

Covers the two questions the operator raised:
  * can the harness remove a Matrix tool completely, live, with hot reload?
  * do improvement proposals and tool gates share ONE approval inbox?

Deterministic, no model, no network, no server. Run: python3 tests/acceptance/v522_matrix_lifecycle.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v522-")
for name, tail in {
    "LONGRUN_DATA_DIR": "data",
    "LONGRUN_CONFIG_DIR": "cfg",
    "LONGRUN_DB": "events.db",
    "LONGRUN_SESSIONS_DIR": "sessions",
    "LONGRUN_GRAPH_DIR": "graphs",
    "LONGRUN_EDITS_DIR": "edits",
    "LONGRUN_RUNS_DIR": "runs",
    "LONGRUN_ROLES_DIR": "roles",
    "LONGRUN_COSTS_DIR": "costs",
    "LONGRUN_THREADS_DIR": "threads",
    "LONGRUN_MATRIX_SRC": "matrix_src",
    "LONGRUN_MATRIX_DOT": "matrix_dot",
    "LONGRUN_APPROVALS": "approvals.json",
}.items():
    os.environ[name] = os.path.join(TMP, tail)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import matrix  # noqa: E402
from longrun.tools import approvals, matrix_guard, registry  # noqa: E402
from longrun.util import improve  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


matrix_guard.ensure_layout(TMP)
_ROOT, MSRC, MDOT = matrix._roots(TMP)

# ---------------------------------------------------------------- create ----
made = matrix.scaffold("tool", "probe.check", "Read the tracked probe value.",
                       repo_root=TMP)
discovered = matrix.discover_tools(TMP)
check("a scaffolded Matrix tool is live after hotload",
      made.get("ok") is True and os.path.isfile(made.get("path") or "")
      and "probe.check" in discovered, made.get("error"))
check("scaffold tells the LLM the exact next lifecycle steps",
      any("fs.edit" in step for step in made.get("next_steps") or [])
      and any("matrix" in step for step in made.get("next_steps") or [])
      and any("hotload" in step for step in made.get("next_steps") or []),
      made.get("next_steps"))
check("the generated schema carries the caller's description",
      "Read the tracked probe value." in
      (discovered.get("probe.check", {}).get("schema", {}).get("description") or ""))

# ------------------------------------------- registry + policy + evidence ----
cfg = registry.load_config()
cfg.setdefault("tools", {})["probe"] = {"enabled": True, "approval": "auto"}
cfg["tools"]["probe.check"] = {"enabled": True, "approval": "auto"}
registry.save_config(cfg)
verify_path = matrix._verified_store_path(TMP)
matrix.write_json(verify_path, {"tool:probe.check": {"kind": "tool",
                                                    "name": "probe.check",
                                                    "sha256": "deadbeef"}})
check("policy and verification records exist before removal",
      "probe.check" in (registry.load_config().get("tools") or {})
      and "tool:probe.check" in (matrix.read_json(verify_path, {}) or {}))

# ---------------------------------------------------------------- remove ----
removed = matrix.remove("tool", "probe.check", repo_root=TMP)
after = matrix.discover_tools(TMP)
check("remove uninstalls the source file",
      removed.get("ok") is True and removed.get("existed") is True
      and not os.path.exists(made.get("path") or ""), removed.get("error"))
check("remove clears discovery without a restart",
      "probe.check" not in after and removed.get("verified_absent") is True,
      removed.get("still_live"))
check("a plain Matrix removal reports a complete uninstall",
      removed.get("complete") is True and removed.get("warnings") == [],
      removed.get("complete"))
check("remove clears the imported module cache",
      "Matrix.tools.probe" not in sys.modules,
      removed.get("module_cache_cleared"))
check("remove clears policy entries from the overlay",
      "probe.check" not in (registry.load_config().get("tools") or {})
      and "probe" not in (registry.load_config().get("tools") or {})
      and (removed.get("policy") or {}).get("removed"),
      removed.get("policy"))
check("remove clears the verification record",
      "tool:probe.check" not in (matrix.read_json(verify_path, {}) or {}),
      removed.get("verified_records_removed"))
check("remove is idempotent and reports that nothing existed",
      matrix.remove("tool", "probe.check", repo_root=TMP).get("existed") is False)

# ------------------------------------------------- multi-subtool module ----
multi_path = os.path.join(MSRC, "tools", "multi.py")
with open(multi_path, "w", encoding="utf-8") as f:
    f.write(
        'TOOL_SCHEMAS = {\n'
        '  "multi.alpha": {"description": "alpha", "type": "object", "properties": {}},\n'
        '  "multi.beta": {"description": "beta", "type": "object", "properties": {}},\n'
        '}\n'
        'def execute(args, run_id=None, subtool=None):\n'
        '    return {"ok": True, "subtool": subtool}\n'
    )
matrix.hotload(TMP)
check("a multi-subtool module is discovered",
      {"multi.alpha", "multi.beta"} <= set(matrix.discover_tools(TMP)))
partial = matrix.remove("tool", "multi.alpha", repo_root=TMP)
check("partial subtool removal is refused with the namespace to use",
      partial.get("ok") is False and "'multi'" in (partial.get("error") or ""),
      partial.get("error"))
whole = matrix.remove("tool", "multi", repo_root=TMP)
check("namespace removal uninstalls every subtool",
      whole.get("ok") is True
      and not ({"multi.alpha", "multi.beta"} & set(matrix.discover_tools(TMP)))
      and whole.get("removed_subtools") == ["multi", "multi.alpha", "multi.beta"],
      whole.get("removed_subtools"))

# ------------------------------------------------------- hook lifecycle ----
hook = matrix.scaffold("hook", "plan", repo_root=TMP)
check("a scaffolded hook becomes active",
      hook.get("ok") is True and "plan" in matrix.discover_hooks(TMP))
hook_removed = matrix.remove("hook", "plan", repo_root=TMP)
check("removing a hook deactivates it live",
      hook_removed.get("ok") is True
      and "plan" not in matrix.discover_hooks(TMP)
      and hook_removed.get("verified_absent") is True,
      hook_removed.get("still_live"))

check("path traversal is rejected",
      matrix.remove("tool", "../evil", repo_root=TMP).get("ok") is False)
check("unknown kinds are rejected",
      matrix.remove("database", "x", repo_root=TMP).get("ok") is False)

# ---------------------------------------------------- tool descriptions ----
remove_schema = (registry.tool_spec("matrix.remove") or {}).get("schema") or {}
scaffold_schema = (registry.tool_spec("matrix.scaffold") or {}).get("schema") or {}
check("matrix.remove is discoverable with exact required fields",
      remove_schema.get("required") == ["name"]
      and set(remove_schema.get("properties") or {}) == {"kind", "name"})
check("matrix.remove is approval-gated",
      (registry.tool_spec("matrix.remove") or {}).get("approval") == "required")
check("lifecycle descriptions name the real next actions",
      "fs.edit" in (scaffold_schema.get("description") or "")
      and "hotload" in (scaffold_schema.get("description") or "")
      and "test" in (scaffold_schema.get("description") or ""))
check("the Matrix prompt documents uninstall",
      "matrix.remove" in matrix.MATRIX_SYSTEM_PROMPT)

# ------------------------------------------------- unified approvals ----
tool_rec = approvals.create("shell.exec", {"command": "printf v522"})
project = improve.propose("project", "- v522 unified inbox rule", ws=TMP)
skill = improve.propose("skill", "v522 skill proposal")
pending = approvals.list_unified("pending")
by_id = {r["id"]: r for r in pending}
check("the inbox contains tool gates and improvement proposals",
      tool_rec["id"] in by_id
      and ("imp:" + project["id"]) in by_id
      and ("imp:" + skill["id"]) in by_id,
      sorted(by_id))
check("the inbox labels provenance instead of mixing queues",
      by_id[tool_rec["id"]]["kind"] == "tool"
      and by_id["imp:" + project["id"]]["kind"] == "improvement"
      and by_id["imp:" + project["id"]]["scope"] == "project")
check("unsupported skill proposals cannot be approved from the inbox",
      # v645 re-pin: skill approval is implemented; a proposal with NO draft
      # folder is the unsupported case now, and it says so.
      by_id["imp:" + skill["id"]]["can_approve"] is False
      and "no draft" in by_id["imp:" + skill["id"]]["blocked_reason"])
check("inbox stats count both pending queues",
      approvals.stats_unified().get("pending_total") == len(pending),
      approvals.stats_unified())

check("one endpoint decides a tool approval",
      approvals.decide_any(tool_rec["id"], "approve").get("ok") is True
      and approvals.get_any(tool_rec["id"]).get("status") == "approved")
skill_decision = approvals.decide_any("imp:" + skill["id"], "approve")
check("one endpoint refuses an unsupported skill approval",
      # v645 re-pin: the reason is now the missing draft, not a missing feature.
      skill_decision.get("ok") is False
      and "nothing to install" in (skill_decision.get("error") or ""),
      skill_decision.get("error"))
project_decision = approvals.decide_any("imp:" + project["id"], "approve")
check("one endpoint approves a project proposal and applies its rule",
      project_decision.get("ok") is True
      and project_decision["approval"].get("status") == "approved")
check("the decided proposal leaves the pending inbox",
      all(r["id"] != "imp:" + project["id"]
          for r in approvals.list_unified("pending")))

# ------------------------------------------------- duplicate proposals ----
dedup = improve.dedupe_proposals([
    {"id": "old", "scope": "skill", "content": "same", "status": "denied", "ts": 1},
    {"id": "new", "scope": "skill", "content": "same", "status": "pending", "ts": 2},
    {"id": "other", "scope": "project", "content": "different", "status": "denied", "ts": 3},
])
check("a pending duplicate wins over a decided copy in the panel",
      [r["id"] for r in dedup] == ["other", "new"], [r["id"] for r in dedup])

print("---")
passed = sum(results)
print("\nv522: %d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)

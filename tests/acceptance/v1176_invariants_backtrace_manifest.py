#!/usr/bin/env python3
"""v1176 — harness invariants, backward tracing, self-description (round 107).

Sources:
  * arXiv:2611.19960 "Anatomy of an Agent Harness" — the corner cases written down
    as invariants with an evidence tag, checked rather than remembered.
  * arXiv:2611.19448 "CLEW" — the failing call is usually the reporter, not the
    cause; trace backward to the earlier action that touched the same resource.
  * arXiv:2611.22299 "Harnesses That Improve Themselves" — a harness that edits
    its runtime must first be able to state what it currently decides.

Deterministic: config dicts are passed in, cards are plain dicts; no server, no
model, no network.

Run: python3 tests/acceptance/v1176_invariants_backtrace_manifest.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1176-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry                # noqa: E402
registry._external_tools = lambda: {}             # noqa: E731
from longrun.harness import invariants, backtrace, manifest  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


# ---- 1. invariants hold on a coherent config --------------------------------
names = list(registry.tool_names())
GOOD_CFG = {
    "sandbox": {"backend": "none"},
    "approvals": {"mode": "required",
                  "kinds": {"memory": "auto", "proposals": "required",
                            "skills": "required", "subagent": "auto"}},
    "runtime": {"keepgoing_max": 8, "no_progress_rounds": 2, "max_wall_secs": 3600},
}
GOOD_SUB = {"max_parallel": 4, "max_per_run": 6, "max_steps": 8, "max_depth": 2,
            "roles": {"researcher": {"brief": "read", "tools": ["fs.read"]}}}

out = invariants.check(tools_cfg=GOOD_CFG, sub_cfg=GOOD_SUB)
status = {r["id"]: r["status"] for r in out["rows"]}
check("the invariants are tagged and counted",
      out["format"] == "longrun-invariants/1" and out["counts"]["total"] >= 8
      and all(r["tag"] in ("tested", "believed", "open") for r in out["rows"]),
      out["counts"])
check("a coherent config violates nothing", out["counts"]["violated"] == 0, status)
check("INV-1 holds for a resolvable role grant", status.get("INV-1") == "holds", status.get("INV-1"))
check("INV-9 is honestly OPEN (never-fired needs traffic)",
      status.get("INV-9") == "open", status.get("INV-9"))

# ---- 2. invariants fire on the corner cases ---------------------------------
BAD_CFG = json.loads(json.dumps(GOOD_CFG))
BAD_CFG["sandbox"]["backend"] = "chroot"
BAD_CFG["runtime"]["max_wall_secs"] = 0
BAD_SUB = json.loads(json.dumps(GOOD_SUB))
BAD_SUB["roles"]["writer"] = {"brief": "writes", "tools": ["fs.red"]}   # typo
BAD_SUB["roles"]["silent"] = {"brief": "", "tools": ["fs.read"]}
BAD_SUB["max_parallel"] = 0
bad = invariants.check(tools_cfg=BAD_CFG, sub_cfg=BAD_SUB)
bstatus = {r["id"]: r for r in bad["rows"]}
check("INV-3 catches an unknown sandbox backend",
      bstatus["INV-3"]["status"] == "violated", bstatus["INV-3"]["detail"])
check("INV-1 catches a role grant with no catalog match",
      bstatus["INV-1"]["status"] == "violated"
      and "writer:fs.red" in bstatus["INV-1"]["detail"], bstatus["INV-1"]["detail"])
check("INV-2 catches a role with no brief",
      bstatus["INV-2"]["status"] == "violated", bstatus["INV-2"]["detail"])
check("INV-6 catches a zero wall clock",
      bstatus["INV-6"]["status"] == "violated", bstatus["INV-6"]["detail"])
check("INV-7 catches an unsatisfiable parallel cap",
      bstatus["INV-7"]["status"] == "violated", bstatus["INV-7"]["detail"])

# ---- 3. backward tracing: the reporter is not the cause ---------------------
A = "/work/data.csv"
CARDS = [
    {"id": "c1", "tool": "fs.read", "ok": True, "args": json.dumps({"path": A})},
    {"id": "c2", "tool": "fs.write", "ok": True,
     "args": json.dumps({"path": A}), "result": "x"},
    {"id": "c3", "tool": "shell.exec", "ok": True,
     "args": json.dumps({"command": "npm test"}), "exit_code": 0},
    {"id": "c4", "tool": "fs.read", "ok": False,
     "args": json.dumps({"path": A}), "error": "ParseError: bad header"},
]
res = backtrace.explain(CARDS, "c4")
check("the failed card is anchored", (res.get("anchor") or {}).get("handle") == "c4")
check("the earlier write to the same file is named",
      any(c["handle"] == "c2" and "earlier-write" in c["reason"]
          for c in res["causes"]), res["causes"])
check("the read of the same file is named too",
      any(c["handle"] == "c1" for c in res["causes"]))
check("an unrelated command is not named",
      not any(c["handle"] == "c3" for c in res["causes"]))
check("the verdict is explained", res["verdict"] == "explained", res["verdict"])

# cascade: an earlier failure is a candidate
CASCADE = [{"id": "a", "tool": "shell.exec", "ok": False, "args": "{}",
            "exit_code": 127, "error": "CommandNotFound: npm"},
           {"id": "b", "tool": "fs.read", "ok": False, "args": "{}",
            "error": "NotFound: dist"}]
c = backtrace.explain(CASCADE, "b")
check("a prior failure is offered as a cascade candidate",
      any(x["handle"] == "a" and x["reason"].startswith("prior-failure")
          for x in c["causes"]), c["causes"])

check("no predecessor means unexplained",
      backtrace.explain([{"id": "x", "tool": "fs.read", "ok": False,
                          "args": "{}", "error": "boom"}], "x")["verdict"]
      == "unexplained")
check("a successful anchor has nothing to explain",
      backtrace.explain([{"id": "y", "tool": "fs.read", "ok": True,
                          "args": "{}", "exit_code": 0}], "y")["verdict"]
      == "anchor-not-failed")
check("an unknown handle is reported, not guessed",
      backtrace.explain(CARDS, "nope")["verdict"] == "anchor-not-found")

# ---- 4. the manifest states the decisions ----------------------------------
man = manifest.build(repo=REPO)
check("the manifest names its decisions",
      man["format"] == "longrun-manifest/1" and len(man["decisions"]) == 6,
      [d["id"] for d in man["decisions"]])
check("each decision names a source",
      all(d.get("source") for d in man["decisions"]))
check("the manifest carries the invariant verdicts",
      man["invariants"]["counts"]["total"] >= 8)

print("\n%d/%d checks passed" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)

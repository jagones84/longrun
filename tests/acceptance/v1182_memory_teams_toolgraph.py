#!/usr/bin/env python3
"""v1182 — memory surfacing, team safety roles, tool dependency graph (round 113).

Sources:
  * arXiv:2611.22179 "RAG in a Trenchcoat" — minimal memory reaches parity; what
    separates designs is what they ENABLE, and presenting the rule more
    prominently closes most of the rule-application gap.
  * arXiv:2611.17820 "Aligning AI Teams" — a designated safety lead plus a
    coordinator-published safety specifications document restore single-agent
    alignment in teams.
  * arXiv:2611.20569 "ToolGraph" — compile parameter-matching and interventional
    evidence into edge confidence; type-level value cannot separate a right tool
    called with a wrong argument.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1182_memory_teams_toolgraph.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1182-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import rule_surface as RS     # noqa: E402
from longrun.harness.checks import team_safety as TS  # noqa: E402
from longrun.harness.checks import tool_graph as TG  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


# ---- 1. memory surfacing ----------------------------------------------------
check("an imperative memory is a rule",
      RS.classify({"text": "Always run the battery before committing."}) == "rule")
check("a demonstrated form is a pattern",
      RS.classify({"text": "1. read\n2. patch\n3. test"}) == "pattern")
check("a stated observation is a fact",
      RS.classify({"text": "The service listens on port 8790."}) == "fact")

hits = [
    {"id": "f2", "text": "Session 42 ended at 10:05.", "ts": "2026-11-19T10:05"},
    {"id": "f1", "text": "Session 41 ended at 09:00.", "ts": "2026-11-19T09:00"},
    {"id": "r1", "text": "Never edit the generated index by hand."},
    {"id": "p1", "text": "```\npytest -q\n```"},
]
out = RS.render(hits, budget_tokens=200)
check("rules are rendered first", out["text"].startswith("RULES (apply these):"), out["text"])
check("patterns follow rules",
      out["text"].index("RULES") < out["text"].index("PATTERNS"), out["text"])
check("facts come last and are chronological",
      out["text"].index("PATTERNS") < out["text"].index("FACTS")
      and out["text"].index("Session 41") < out["text"].index("Session 42"), out["text"])
check("every rendered row keeps its provenance",
      "[r1]" in out["text"] and "[f1]" in out["text"], out["text"])
check("the rule is named prominent", out["prominent"] == ["r1"], out["prominent"])
check("counts state each tier", out["counts"]["rules"] == 1
      and out["counts"]["patterns"] == 1 and out["counts"]["facts"] == 2, out["counts"])

tight = RS.render(hits, budget_tokens=10)
check("a tight budget drops facts first", tight["counts"]["facts"] < 2, tight["counts"])
check("a tight budget never drops the rule",
      "Never edit the generated index" in tight["text"], tight["text"])
check("an unavoidable overflow is reported, not hidden", tight["over_budget"] is True, tight)
check("empty rows and unknown shapes are skipped, never invented",
      RS.render([{}, "x", {"text": "  "}])["counts"] ==
      {"rules": 0, "patterns": 0, "facts": 0, "dropped": 0})

# ---- 2. team safety --------------------------------------------------------
COVERED = {
    "coordinator": "pm",
    "members": [{"id": "pm", "role": "coordinator"}, {"id": "a1", "role": "coder"},
                {"id": "a2", "role": "coder"}],
    "safety_lead": "a1",
    "safety_doc": {"author": "pm", "targets": "no data loss", "owners": "a1",
                   "checks": "restart replay"},
    "jobs": [{"id": "j1", "safety": "checkpoint before restart"}],
}
res = TS.audit(COVERED)
check("a team with a lead and a published spec is covered",
      res["verdict"] == "covered" and res["findings"] == [], res)
check("the brief states coverage in one line",
      TS.brief(COVERED).startswith("team-safety: covered"), TS.brief(COVERED))

nolead = TS.audit({**COVERED, "safety_lead": ""})
check("no designated lead is uncovered",
      nolead["verdict"] == "uncovered"
      and nolead["findings"][0]["kind"] == "missing-safety-lead", nolead)
selflead = TS.audit({**COVERED, "safety_lead": "pm"})
check("the coordinator cannot also be the safety lead",
      any(f["kind"] == "lead-is-coordinator" for f in selflead["findings"]), selflead)
outsider = TS.audit({**COVERED, "safety_lead": "zz"})
check("a lead outside the roster is flagged",
      any(f["kind"] == "lead-not-a-member" for f in outsider["findings"]), outsider)
nodoc = TS.audit({**COVERED, "safety_doc": {}})
check("no safety document is uncovered",
      nodoc["verdict"] == "uncovered"
      and any(f["kind"] == "missing-safety-doc" for f in nodoc["findings"]), nodoc)
wrongauthor = TS.audit({**COVERED, "safety_doc": {**COVERED["safety_doc"], "author": "a2"}})
check("a document not published by the coordinator is flagged",
      any(f["kind"] == "doc-not-published-by-coordinator"
          for f in wrongauthor["findings"]), wrongauthor)
partial = TS.audit({**COVERED, "safety_doc": {**COVERED["safety_doc"], "checks": ""}})
check("an incomplete document is the softer verdict",
      partial["verdict"] == "incomplete"
      and any(f["kind"] == "incomplete-safety-doc" for f in partial["findings"]), partial)
unscoped = TS.audit({**COVERED, "jobs": [{"id": "j1"}]})
check("a job without a safety scope is reported",
      unscoped["verdict"] == "incomplete"
      and any(f["kind"] == "job-without-safety-scope" for f in unscoped["findings"]), unscoped)

# ---- 3. tool dependency graph ----------------------------------------------
CATALOG = [
    {"name": "repo.read", "inputs": [{"name": "path", "type": "path"}],
     "outputs": [{"name": "text", "type": "text"}]},
    {"name": "code.search", "inputs": [{"name": "query", "type": "text"}],
     "outputs": [{"name": "hits", "type": "hits"}]},
    {"name": "edit.apply", "inputs": [{"name": "patch", "type": "hits"}],
     "outputs": [{"name": "diff", "type": "diff"}]},
]
g = TG.build(CATALOG)
edge = {(e["from"], e["to"]): e for e in g["edges"]}
check("parameter matching proposes an edge between compatible tools",
      ("repo.read", "code.search") in edge
      and any("parameter-matching" in r for r in edge[("repo.read", "code.search")]["reasons"]))
check("an incompatible pair gets no parameter edge",
      ("edit.apply", "repo.read") not in edge)

g2 = TG.build(CATALOG, transitions=[
    {"from": "code.search", "to": "edit.apply", "ok": True},
    {"from": "code.search", "to": "edit.apply", "ok": True},
], probes=[{"from": "code.search", "to": "edit.apply", "ok": True, "without_ok": False}])
e2 = next(e for e in g2["edges"] if e["from"] == "code.search" and e["to"] == "edit.apply")
check("observed successes and an interventional probe raise the edge",
      e2["confidence"] == 1.0 and e2["observations"] == 2
      and any("interventional: needed" in r for r in e2["reasons"]), e2)

g3 = TG.build(CATALOG, probes=[{"from": "code.search", "to": "edit.apply",
                                "ok": True, "without_ok": True}])
e3 = next(e for e in g3["edges"] if e["from"] == "code.search" and e["to"] == "edit.apply")
check("a probe that works without the predecessor lowers the edge",
      e3["confidence"] < 0.4 and any("not needed" in r for r in e3["reasons"]), e3)

# Round 121: a declared effect contributes a typed writer->reader edge.
TYPED = [
    {"name": "mem.store", "effect": "append", "writes": ["memory"]},
    {"name": "mem.recall", "effect": "read", "reads": ["memory"]},
    {"name": "file.dump", "effect": "write", "writes": ["file"]},
]
gt = TG.build(TYPED)
tedges = {(e["from"], e["to"]): e for e in gt["edges"]}
check("a declared writer precedes the reader of that resource",
      ("mem.store", "mem.recall") in tedges
      and any(r == "effect:memory" for r in tedges[("mem.store", "mem.recall")]["reasons"]),
      tedges.get(("mem.store", "mem.recall")))
check("two writers of the same resource are not chained",
      ("mem.store", "file.dump") not in tedges and ("file.dump", "mem.store") not in tedges)

ranked = TG.rank(g2, after="code.search")
check("ranking returns the strongest next tool after a given one",
      ranked and ranked[0]["tool"] == "edit.apply" and ranked[0]["confidence"] == 1.0, ranked)

fb = TG.feedback(g2, "fix the failing test", "edit.apply", state_types=["hits"])
check("feedback names the required arguments", "patch" in fb["text"], fb["text"])
check("feedback lists what the state already provides",
      fb["missing_inputs"] == [] and fb["known"] is True, fb)
check("feedback always warns that types cannot judge argument values",
      "wrong argument" in fb["text"], fb["text"])
missing = TG.feedback(g2, "fix", "edit.apply", state_types=[])
check("a missing input is named explicitly", missing["missing_inputs"] == ["patch"], missing)
unknown = TG.feedback(g2, "fix", "nope")
check("an unknown candidate is reported, not guessed",
      unknown["known"] is False and "no catalog entry" in unknown["text"], unknown)

print("\n%d/%d checks passed" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)

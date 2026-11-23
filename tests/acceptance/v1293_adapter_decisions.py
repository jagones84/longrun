#!/usr/bin/env python3
"""v1293 — an approved improvement names the harness field it edits (RSI I-6).

I-5 gave the loop the paper's genotype vocabulary (arXiv:2611.25380 §3.4) but an
approved proposal still carried only prose: nothing said whether the change moved
the system prompt, a tool schema or a skill, and there was no way to read the
loop's own genotype history back. Contract:

  A `summary()` maps a record's scope onto its field, metadata only (no body)
  B approving a project rule stamps `adapter` and writes one `adapter` ledger row
  C approving a skill bundle stamps the `skill` field, without copying bytes
  D a scope that edits no harness field is approved WITHOUT an adapter claim
  E a denied proposal records no adapter
  F `history()` reads the real ledger back: per-field/domain counts and the last edit
  G `history()` aggregates supplied rows (domains included) and fails open on none

Deterministic: no model, no network, isolated temp dirs.
Run: python3 tests/acceptance/v1293_adapter_decisions.py
"""
import hashlib
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1293-")
for _k in ("DATA_HOME", "DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "PROPOSALS_DIR",
           "IMPROVEMENT_DIR", "SKILLS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k.lower())
os.makedirs(os.environ["LONGRUN_DATA_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import domain_adapter as DA   # noqa: E402
from longrun.util import improve                    # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def adapter_rows(pid=None):
    return [r for r in improve.ledger_tail(300)
            if r.get("kind") == "adapter" and (pid is None or r.get("proposal") == pid)]


# ---- A: summary is metadata, keyed by the scope ----------------------------
check("A1 a project record is the system prompt",
      DA.summary({"id": "p1", "scope": "project"})["fields"] == ["system_prompt"])
check("A2 a matrix record is the tool schema",
      DA.summary({"id": "p2", "scope": "matrix"})["fields"] == ["tool_schema"])
check("A3 the domain is slugged, and defaults to general",
      DA.summary({"id": "p3", "scope": "skill", "domain": "SWE Domain"})["domain"]
      == "swe-domain"
      and DA.summary({"id": "p4", "scope": "skill"})["domain"] == "general")
check("A4 a scope that edits no field has no adapter",
      DA.summary({"id": "p5", "scope": "memory"}) is None
      and DA.summary({"id": "p6", "scope": "code"}) is None)
check("A5 the summary carries no body",
      set(DA.summary({"id": "p7", "scope": "skill"})) == {"name", "domain", "fields"},
      DA.summary({"id": "p7", "scope": "skill"}))

# ---- B: a project approval is stamped and audited -------------------------
WS = os.path.join(TMP, "ws")
os.makedirs(WS, exist_ok=True)
proj = improve.propose("project", "- Verify before claiming done.\n", ws=WS,
                       reason="v1293 fixture")
res = improve.decide(proj["id"], "approve")
check("B1 the approval succeeds", res.get("ok") is True, res)
rec = improve.get_proposal(proj["id"]) or {}
check("B2 the record carries the adapter it edits",
      (rec.get("adapter") or {}).get("fields") == ["system_prompt"],
      rec.get("adapter"))
rows = adapter_rows(proj["id"])
check("B3 one adapter row is written, naming the field and the domain",
      len(rows) == 1 and rows[0].get("field") == "system_prompt"
      and rows[0].get("domain") == "general" and rows[0].get("scope") == "project",
      rows)

# ---- C: a skill bundle is stamped without copying its bytes ----------------
body = "# Skill\n\nRun the failing test first.\n"
art = {"kind": "skill_file", "name": "verify-first",
       "target": "skills/created/verify-first/SKILL.md", "content": body,
       "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest()}
sk = improve.propose("skill", "install verify-first", artifacts=[art])
res_c = improve.decide(sk["id"], "approve")
check("C1 the bundle installs", res_c.get("ok") is True, res_c)
rec_c = improve.get_proposal(sk["id"]) or {}
check("C2 the record edits the skill field",
      (rec_c.get("adapter") or {}).get("fields") == ["skill"], rec_c.get("adapter"))
check("C3 the adapter is metadata: no body, no edit map",
      "content" not in (rec_c.get("adapter") or {})
      and "edits" not in (rec_c.get("adapter") or {}), rec_c.get("adapter"))
check("C4 the ledger row names the skill field",
      [r for r in adapter_rows(sk["id"]) if r.get("field") == "skill"],
      adapter_rows(sk["id"]))

# ---- D: a scope with no harness field makes no claim ----------------------
mem = improve.propose("memory", "a note that changes no harness field")
res_d = improve.decide(mem["id"], "approve")
rec_d = improve.get_proposal(mem["id"]) or {}
check("D1 the approval still succeeds", res_d.get("ok") is True, res_d)
check("D2 no adapter is claimed", "adapter" not in rec_d, rec_d.get("adapter"))
check("D3 no adapter row is written", adapter_rows(mem["id"]) == [],
      adapter_rows(mem["id"]))

# ---- E: a denial records no adapter ---------------------------------------
den = improve.propose("global", "- A rule nobody approved.\n")
improve.decide(den["id"], "deny")
check("E1 a denied proposal has no adapter",
      "adapter" not in (improve.get_proposal(den["id"]) or {})
      and adapter_rows(den["id"]) == [])

# ---- F: the history reads the real ledger back ----------------------------
hist = DA.history()
check("F1 both approvals are in the history", hist.get("count") == 2, hist)
check("F2 the counts are per field",
      hist["fields"].get("system_prompt", {}).get("count") == 1
      and hist["fields"].get("skill", {}).get("count") == 1, hist.get("fields"))
check("F3 the newest edit is named", (hist.get("last") or {}).get("field") == "skill",
      hist.get("last"))
check("F4 every edit names its proposal",
      all(r.get("proposal") for r in hist.get("edits") or []), hist.get("edits"))

# ---- G: supplied rows, domains, and the empty case ------------------------
rows = [{"kind": "adapter", "ts": 10, "field": "tool_schema", "domain": "swe",
         "proposal": "a", "name": "a"},
        {"kind": "adapter", "ts": 20, "field": "tool_schema", "domain": "office",
         "proposal": "b", "name": "b"},
        {"kind": "decide", "ts": 30, "field": "skill"}]
got = DA.history(rows=rows)
check("G1 only adapter rows count", got.get("count") == 2, got)
check("G2 one field, two domains", got["fields"]["tool_schema"]["count"] == 2
      and set(got["domains"]) == {"swe", "office"}, (got["fields"], got["domains"]))
check("G3 the newest edit is first",
      [r["proposal"] for r in got["edits"]] == ["b", "a"], got["edits"])
empty = DA.history(rows=[])
check("G4 an empty history is not an error",
      empty.get("ok") is True and empty.get("count") == 0
      and empty.get("last") is None, empty)

print("---")
print("v1293: %d/%d PASS" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)

#!/usr/bin/env python3
"""v1292 — domain-scoped harness adapters compose, and may not cost another domain (RSI I-5).

Source: B. Chen et al., *Beyond Weight Updates: Evolving Agent Harnesses for
Domain Specialization*, arXiv:2611.25380 (2026), §3.4–§3.5 and Eq. 4. The paper
optimises the harness instead of the weights: a genotype is a STRUCTURED set of
named fields, a round edits one field, and the output is a domain-scoped adapter.
Adapters compose when their fields are disjoint; an overlapping field is a
right-biased override, recorded, never a silent collision. Eq. 4's retention
constraint says a specialisation may not destroy prior capability — the paper
measures it as the off-target columns staying near the base (Table 4).

Longrun had the pieces (rules proposals, mined skills, Matrix bundles, registry
deltas) but no name for the composed object and no check for collisions or
cross-domain regressions. Contract:

  A `adapter()` validates: fixed field vocabulary, non-empty body, name/domain slugs
  B disjoint adapters compose into one genotype, no overrides
  C an overlapping field is a right-biased override, recorded with both names
  D `retention()` refuses a specialisation that drops another domain beyond tol
  E `from_proposal`/`from_candidate` map the existing records onto their field
  F `genotype()` composes a round and names the rows that edit no field
  G the harness cycle report carries the genotype of the candidates it supported

Deterministic: no model, no network, isolated temp dirs.
Run: python3 tests/acceptance/v1292_domain_adapters.py
"""
import json
import os
import sys
import tempfile
from unittest.mock import patch

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1292-")
for _k in ("CONFIG_DIR", "DATA_HOME", "DATA_DIR", "HARNESS_DIR", "SESSIONS_DIR",
           "PROPOSALS_DIR", "IMPROVEMENT_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import domain_adapter as DA   # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def ad(name, domain, edits):
    got = DA.adapter(name, domain, edits)
    return got.get("adapter") if got.get("ok") else got


# ---- A: validation ----------------------------------------------------------
good = ad("My Adapter!", "SWE Domain", {"skill": "run the failing test first"})
check("A1 a valid adapter is accepted with slugged name/domain",
      isinstance(good, dict) and good.get("name") == "my-adapter"
      and good.get("domain") == "swe-domain" and good.get("fields") == ["skill"], good)
check("A2 no edits is refused", DA.adapter("x", "d", {}).get("ok") is False)
check("A3 an unknown field is refused, naming the vocabulary",
      DA.adapter("x", "d", {"weights": "x"}).get("ok") is False
      and "tool_schema" in str(DA.adapter("x", "d", {"weights": "x"}).get("error")),
      DA.adapter("x", "d", {"weights": "x"}))
check("A4 an empty body is refused",
      DA.adapter("x", "d", {"skill": "   "}).get("ok") is False)
check("A5 an oversized body is refused, not silently cut",
      DA.adapter("x", "d", {"skill": "x" * (DA.MAX_EDIT + 1)}).get("ok") is False)
check("A6 a non-dict edit map is refused",
      DA.adapter("x", "d", "skill").get("ok") is False)

# ---- B: disjoint composition ------------------------------------------------
a = ad("a", "swe", {"system_prompt": "always read the test"})
b = ad("b", "swe", {"skill": "patch then run the check"})
mixed = DA.compose([a, b])
check("B1 two disjoint adapters fill two fields",
      mixed.get("ok") is True and mixed.get("fields") == ["skill", "system_prompt"],
      mixed)
check("B2 nothing is overridden", mixed.get("overrides") == [], mixed.get("overrides"))
check("B3 the genotype keeps each body under its author",
      mixed["genotype"]["skill"]["body"] == "patch then run the check"
      and mixed["genotype"]["skill"]["by"] == "b", mixed.get("genotype"))

# ---- C: right-biased override ----------------------------------------------
c = ad("c", "swe", {"skill": "check FIRST, then patch"})
one = DA.compose([b, c])
two = DA.compose([c, b])
check("C1 an overlap is recorded as an override, with both names",
      one.get("overrides") == [{"field": "skill", "from": "b", "to": "c"}],
      one.get("overrides"))
check("C2 the later adapter wins", one["genotype"]["skill"]["by"] == "c", one["genotype"])
check("C3 order matters, and the record follows the order",
      two["genotype"]["skill"]["by"] == "b"
      and two.get("overrides") == [{"field": "skill", "from": "c", "to": "b"}],
      (two.get("overrides"), two["genotype"]["skill"]["by"]))
check("C4 conflicts names the shared fields", DA.conflicts(b, c) == ["skill"],
      DA.conflicts(b, c))
check("C5 an invalid member refuses the whole load",
      DA.compose([a, {"name": "bad", "edits": {"weights": "x"}}]).get("ok") is False)

# ---- D: the retention constraint (Eq. 4) -----------------------------------
before = {"swe": {"ok": 8, "runs": 10}, "office": {"ok": 7, "runs": 10}}
same = {"swe": {"ok": 9, "runs": 10}, "office": {"ok": 7, "runs": 10}}
check("D1 its own gain with no off-target change is retained",
      DA.retention(before, same).get("ok") is True, DA.retention(before, same))
hurt = {"swe": {"ok": 10, "runs": 10}, "office": {"ok": 6, "runs": 10}}
rep = DA.retention(before, hurt)
check("D2 a gain in one domain does not hide a loss in another",
      rep.get("ok") is False and rep["regressions"][0]["domain"] == "office"
      and rep["regressions"][0]["delta"] == -0.1, rep)
check("D3 a stated tolerance can absorb it, and is reported",
      DA.retention(before, hurt, tolerance=0.2).get("ok") is True,
      DA.retention(before, hurt, tolerance=0.2))
check("D4 a domain with no evidence on one side is skipped, not guessed",
      DA.retention({"swe": {"ok": 8, "runs": 10}}, {"swe": {"ok": 8, "runs": 10},
                                                     "new": {"ok": 1, "runs": 1}})
      .get("skipped") == ["new"])
check("D5 plain rates are accepted",
      DA.retention({"a": 0.7}, {"a": 0.71}).get("ok") is True)
check("D6 no evidence compares nothing and passes",
      DA.retention({}, {}).get("ok") is True and DA.retention({}, {})["compared"] == [])

# ---- E: the existing records map onto their field --------------------------
got = DA.from_proposal({"id": "p1", "scope": "skill", "content": "do x",
                        "domain": "swe"})
check("E1 a skill proposal is the skill field, in its own domain",
      got and got["fields"] == ["skill"] and got["domain"] == "swe", got)
check("E2 project/global edit the system prompt",
      DA.from_proposal({"id": "p2", "scope": "project", "content": "x"})["fields"]
      == ["system_prompt"]
      and DA.from_proposal({"id": "p3", "scope": "global", "content": "x"})["fields"]
      == ["system_prompt"])
check("E3 matrix/registry edit the tool schema",
      DA.from_proposal({"id": "p4", "scope": "matrix", "content": "x"})["fields"]
      == ["tool_schema"]
      and DA.from_proposal({"id": "p5", "scope": "registry", "content": "x"})["fields"]
      == ["tool_schema"])
check("E4 a scope that edits no harness field maps to None",
      DA.from_proposal({"id": "p6", "scope": "memory", "content": "x"}) is None
      and DA.from_proposal({"id": "p7", "scope": "code", "content": "x"}) is None)
check("E5 an artifact-only proposal takes its body from the artifacts",
      DA.from_proposal({"id": "p8", "scope": "skill", "content": "",
                        "artifacts": [{"content": "# body\n"}]})["fields"] == ["skill"])
check("E6 a missing domain is NOT the workspace path",
      DA.from_proposal({"id": "p9", "scope": "skill", "content": "x",
                        "ws": "/home/u/repo"})["domain"] == "general",
      DA.from_proposal({"id": "p9", "scope": "skill", "content": "x",
                        "ws": "/home/u/repo"}))
check("E7 a candidate kind maps the same way",
      DA.from_candidate({"kind": "guardrail", "name": "g", "content": "x"})["fields"]
      == ["system_prompt"]
      and DA.from_candidate({"kind": "matrix_tool", "name": "m",
                             "content": "x"})["fields"] == ["tool_schema"])

# ---- F: a round's genotype --------------------------------------------------
gen = DA.genotype([{"kind": "guardrail", "name": "g", "content": "a"},
                   {"kind": "skill", "name": "s", "content": "b"},
                   {"kind": "unknown", "name": "u", "content": "c"}], domain="swe")
check("F1 the round names both fields", gen.get("fields") == ["skill", "system_prompt"], gen)
check("F2 a row that edits no field is named, not dropped", gen.get("skipped") == ["u"], gen)
check("F3 the domain is carried", gen.get("domain") == "swe", gen)

# ---- G: the harness cycle report carries it ---------------------------------
from longrun.harness import cycle                   # noqa: E402
from longrun.harness.execution import probe         # noqa: E402

workspace = tempfile.mkdtemp(dir=TMP)
with open(os.path.join(workspace, "input.txt"), "w", encoding="utf-8") as f:
    f.write("input")
BASE = {"run_id": "base", "workspace": workspace, "goal": "Read inputs",
        "model": "m", "harness": {}, "budget": {},
        "steps": [{"tool": "fs.read", "ok": False, "error": "missing input"}],
        "deliverables": [], "files_touched": []}
CANDS = [{"kind": "guardrail", "name": "a", "content": "Inventory inputs."},
         {"kind": "skill", "name": "b", "content": "Read inputs first."}]
CONFIG = dict(probe.DEFAULTS, enabled=True, max_candidates=2)


def _editor(_messages):
    return json.dumps({"candidates": CANDS}), "", "m"


def _runner(plan, _timeout):
    return {"record": dict(BASE, run_id="t-%d" % len(plan["staged"]),
                           steps=[{"tool": "fs.read", "ok": True}])}, ""


with patch.object(cycle.record_mod, "build", return_value=BASE):
    result = cycle.run("session", dry_run=False, c=CONFIG, call=_editor, runner=_runner)
gen = result.get("genotype") or {}
check("G1 the cycle report states the fields the round edits",
      gen.get("fields") == ["skill", "system_prompt"], gen)
check("G2 the two candidates compose without an override",
      gen.get("overrides") == [] and gen.get("adapters") == ["a", "b"], gen)
check("G3 the report is the persisted one (JSON round-trip)",
      (cycle.last() or {}).get("genotype") == gen, cycle.last())
check("G4 a refusal path still reports (dry run has no genotype claim)",
      "genotype" not in cycle.run("session", dry_run=True, c=CONFIG), cycle.last())

print("---")
print("v1292: %d/%d PASS" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)

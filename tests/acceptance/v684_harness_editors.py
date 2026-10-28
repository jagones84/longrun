#!/usr/bin/env python3
"""v684 — H2-4 two scoped editors, propose-only.

Harness² splits its editor in two: an INVARIANT editor that owns how the agent
works (tool use, procedure, completion) and a DOMAIN editor that owns the subject
matter (`papers/harness2/harness2_2610.14224.txt:279-284`, Prompt 1 `:1953-1979`).
Scoping is measured: removing it costs 2.9 / 3.7 points (Table 3, `:628-643`).

The governance pin matters more than the prompt text: Longrun's self-improvement
policy already forbids the agent writing harness CODE (`util/improve.py:21-27`),
so an editor may only emit PROPOSALS (skill / project rule / global rule) and the
operator decides. This test asserts that boundary, not just the happy path.

  A  each scope produces a different prompt
  B  the prompt carries the contrast + bounded library rows, never observations
  C  a skill candidate becomes an `improve.propose` call with origin="harness"
  D  a code/plugin candidate is rejected (no proposal written)
  E  an unchanged / incomparable / absent contrast produces nothing at all
  F  an oversized candidate is rejected
  G  the prompt is deterministic

No model, no network, no server: the model call is injected.
"""
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v684-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "DATA_DIR", "HARNESS_DIR", "RUNS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_HOOKS"] = os.path.join(TMP, "hooks.yaml")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import editors as E  # noqa: E402
from longrun.util import improve as IMP  # noqa: E402

results = []


def check(name, ok, detail=""):
    """Record one assertion (repo convention)."""
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


RECORD = {
    "schema": 1, "run_id": "base", "session_id": "s", "goal": "Reconcile schedule and budget",
    "ts": 0.0, "model": "m", "workspace": "/ws",
    "harness": {"revision": "rev", "prompt": None,
                "skills": {"count": 0, "sha256": "x"}, "hooks": {"count": 0, "sha256": "y"},
                "config": {}, "overlay": None},
    "budget": {"steps": 3, "seconds": 9.0, "tokens": 100},
    "steps": [
        {"n": 1, "tool": "fs.read", "ok": True, "error": "", "exit_code": 0, "ts": 1.0,
         "node": None, "backend": "", "args_keys": ["path"], "args_len": 20,
         "args_digest": "d1", "obs_chars": 40},
        {"n": 2, "tool": "shell", "ok": False, "error": "exit 7 connection refused",
         "exit_code": 7, "ts": 2.0, "node": None, "backend": "host",
         "args_keys": ["command"], "args_len": 90, "args_digest": "d2", "obs_chars": 0},
    ],
    "files_touched": [],
    "deliverables": [],
}
CONTRAST = {
    "comparable": True, "verdict": "regressed",
    "steps": {"base": 3, "cand": 3, "saved": 0},
    "tools": {"base": {"fs.read": 1, "shell": 1}, "cand": {}, "same": True},
    "errors": {"base": 1, "cand": 2, "fixed": [], "introduced": ["exit # connection refused"],
               "classes_base": {}, "classes_cand": {}},
    "files": {"only_base": [], "only_cand": [], "common": 0},
    "deliverables": {"base": 0, "cand": 0, "only_base": [], "only_cand": [], "changed": []},
    "budget": {"steps": 0, "seconds": 0.0, "tokens": 0},
    "harness": {"changed": []},
    "reasons": ["new error class(es): exit # connection refused"],
}


def stub(candidates):
    """A model call that returns one JSON object (no network)."""
    def call(_msgs, *_a, **_k):
        return json.dumps({"candidates": candidates}), "", "stub-model"
    return call


SKILL = {"kind": "skill", "name": "reconcile-budget",
         "content": "---\nname: reconcile-budget\n---\nWhen the task reconciles two "
                    "spreadsheets, inventory every file before writing.\n",
         "why": "the run never inventoried inputs"}
CODE = {"kind": "code", "name": "hook", "content": "print('x')", "why": "enforce"}
HUGE = {"kind": "skill", "name": "huge", "content": "x" * (E.MAX_CONTENT + 10), "why": "big"}

# --------------------------------------------------------------- A: prompts --
pinv = E.build_prompt("invariant", RECORD, CONTRAST)
pdom = E.build_prompt("domain", RECORD, CONTRAST)
check("A1 the two scopes produce different prompts", pinv != pdom and len(pinv) > 200)
check("A2 the invariant prompt owns procedure, the domain prompt owns the subject",
      "how the agent works" in pinv.lower() and "subject" in pdom.lower())

# ------------------------------------------------------------- B: evidence ---
check("B1 the prompt carries the contrast evidence", "connection refused" in pinv)
check("B2 the prompt names the goal", "Reconcile schedule and budget" in pinv)
check("B3 observations are never inlined (only counts)",
      "[shell] exit" not in pinv and "args_digest" not in pinv and "obs_chars" not in pinv)
lib = [{"id": "reconcile-1", "task_kind": "budget reconciliation", "lesson": "inventory inputs first",
        "components": ["SKILL.md"]}]
plib = E.build_prompt("domain", RECORD, CONTRAST, library_rows=lib)
check("B4 library rows are listed as a bounded index", "reconcile-1" in plib and "SKILL.md" in plib)

# --------------------------------------------------------------- C: propose --
before = len(IMP.list_proposals())
out = E.propose("domain", RECORD, CONTRAST, call=stub([SKILL]), domain="office")
after = IMP.list_proposals()
check("C1 one skill candidate becomes one proposal",
      len(out["proposals"]) == 1 and len(after) == before + 1, out)
rec = [p for p in after if p.get("id") in out["proposals"]]
check("C2 the proposal is a SKILL scope with origin=harness",
      bool(rec) and rec[0].get("scope") == "skill" and rec[0].get("origin") == "harness",
      rec[0].get("scope") if rec else None)
check("C3 the prompt that produced it was recorded as the reason",
      bool(rec) and "inventoried inputs" in (rec[0].get("reason") or ""))

# --------------------------------------------------------------- D: refusal --
out_code = E.propose("invariant", RECORD, CONTRAST, call=stub([CODE]), domain="office")
check("D1 a code candidate is rejected, not proposed",
      out_code["proposals"] == [] and out_code["rejected"], out_code)
check("D2 the refusal names the kind", "code" in json.dumps(out_code["rejected"]))
check("D3 no proposal was written for it", len(IMP.list_proposals()) == before + 1)

# ----------------------------------------------------------------- E: gates --
quiet = dict(CONTRAST, verdict="unchanged")
check("E1 an unchanged contrast produces no editor run",
      E.propose("invariant", RECORD, quiet, call=stub([SKILL]))["skipped"] == "no contrast")
incomp = dict(CONTRAST, comparable=False, verdict="incomparable")
check("E2 an incomparable contrast is refused",
      E.propose("invariant", RECORD, incomp, call=stub([SKILL]))["skipped"] == "incomparable")
check("E3 an absent contrast is refused",
      E.propose("invariant", RECORD, {}, call=stub([SKILL]))["skipped"] == "no contrast")

# --------------------------------------------------------------- F: size -----
out_huge = E.propose("invariant", RECORD, CONTRAST, call=stub([HUGE]), domain="office")
check("F1 an oversized candidate is rejected", out_huge["proposals"] == [], out_huge.get("rejected"))
check("F2 nothing extra was written", len(IMP.list_proposals()) == before + 1)

# -------------------------------------------------------- G: determinism -----
check("G1 the same inputs produce the same prompt",
      E.build_prompt("invariant", RECORD, CONTRAST) == pinv)

shutil.rmtree(TMP, ignore_errors=True)

print("\n%d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)

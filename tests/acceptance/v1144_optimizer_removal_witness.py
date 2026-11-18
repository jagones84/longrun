#!/usr/bin/env python3
"""v1144 — a removal the harness can refute is not a proposal (round 78).

Rounds 77 and 78 measured the same failure twice: the proposer called the
`localhost` and `127.0.0.1` control-API guards "duplicates" and moved to delete
one — with both rules' own `why` in the prompt. Resemblance is not coverage, so
the check is an ORACLE, not more prose: build an input from the removed rule's
own literals, then ask the compiled regexes. If the removed rule matches an input
and no remaining rule does, the removal narrows the policy and is not submitted.

Contract:
  A `_removal_witness` refutes a non-duplicate and stays silent on a real one
  B `_uncovered_removal` reads the live list and honours `add` (a replacement)
  C `run()` refuses the refuted delta and still submits a covered replacement

Deterministic: the model is stubbed; the live list is the shipped config.
Run: python3 tests/acceptance/v1144_optimizer_removal_witness.py
"""
import json
import os
import re
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1144-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_OPTIMIZER_LOG"] = os.path.join(TMP, "optimizer_runs.jsonl")
os.makedirs(os.environ["LONGRUN_DATA_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.evolve import optimizer as O      # noqa: E402
from longrun.tools import registry as R        # noqa: E402
from longrun.util import improve as I          # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


LOCAL = (r"(?:curl|wget)[^\n]*localhost[^\n]*/api/"
         r"(jobs|agents|teams|architect|tools|settings|docs|fs|edits)")
LOOP = (r"(?:curl|wget)[^\n]*127\.0\.0\.1[^\n]*/api/"
        r"(jobs|agents|teams|architect|tools|settings|docs|fs|edits)")
BROADER = r"(?:curl|wget)[^\n]*(localhost|127\.0\.0\.1)[^\n]*/api/(jobs|agents)"

# ---- A) the witness oracle ---------------------------------------------------
_w = O._removal_witness(LOCAL, [LOOP])
check("A1 the measured pair yields a witness", bool(_w), _w)
check("A2 the witness is what the removed rule matches",
      bool(_w) and bool(re.search(LOCAL, _w)), _w)
check("A3 and what the remaining rule does NOT match",
      bool(_w) and not re.search(LOOP, _w), _w)
check("A4 an identical duplicate yields no witness",
      O._removal_witness("LONGRUN_TOKEN", ["LONGRUN_TOKEN"]) is None)
check("A5 a broader remaining rule covers it",
      O._removal_witness(r"\bcat\b", [r"\b(cat|dog)\b"]) is None)
check("A6 a pattern with no literal yields no witness",
      O._removal_witness(r"^.*$", []) is None)
check("A7 an uncompilable pattern yields no witness",
      O._removal_witness("[", []) is None)
check("A8 no remaining rules at all yields a witness",
      bool(O._removal_witness("LONGRUN_TOKEN", [])), )

# ---- B) the delta-level check -----------------------------------------------
_orig_spec = R.tool_spec


def _spec(name, *a, **k):
    return {"deny": ["LONGRUN_TOKEN", LOCAL, LOOP]} if name == "shell.exec" else None


R.tool_spec = _spec
try:
    check("B1 a deny removal that leaves an input unguarded is refused",
          (O._uncovered_removal({"target": "shell.exec", "field": "deny",
                                 "remove": [LOCAL]}) or {}).get("witness") is not None,
          O._uncovered_removal({"target": "shell.exec", "field": "deny",
                                "remove": [LOCAL]}))
    check("B2 a non-deny field is never checked",
          O._uncovered_removal({"target": "shell.exec", "field": "approval",
                                "remove": [LOCAL]}) is None)
    check("B3 no `remove` is fine",
          O._uncovered_removal({"target": "shell.exec", "field": "deny",
                                "add": ["x"]}) is None)
    check("B4 an `add` that covers the input makes it a replacement, not a removal",
          O._uncovered_removal({"target": "shell.exec", "field": "deny",
                                "remove": [LOCAL], "add": [BROADER]}) is None)
    check("B5 an unknown target is not a refusal",
          O._uncovered_removal({"target": "no.such.tool", "field": "deny",
                                "remove": [LOCAL]}) is None)
finally:
    R.tool_spec = _orig_spec


# ---- C) run() integration ----------------------------------------------------
O._read_trace = lambda sid: {"tokens": 10, "steps": 2, "outcome": "ok", "model": "m"}
O._read_policy_hits = lambda: {}
O._read_job_cost = lambda jid: {}
O._read_feedback = lambda sid: {}


def reply(delta):
    O._call_model = lambda prompt, model=None: json.dumps(delta)


reply({"target": "shell.exec", "field": "deny", "remove": [LOCAL],
       "reason": "the localhost rule duplicates the 127.0.0.1 one"})
_r = O.run("v1144-a")
check("C1 the refuted removal is a skip, not a proposal",
      _r.get("skip") is True and not _r.get("proposal_id"), _r.get("proposal_id"))
check("C2 its reason quotes the witness and the refutation",
      "not covered" in (_r.get("reason") or "") and "NO other live deny rule"
      in (_r.get("reason") or ""), _r.get("reason"))
check("C3 the model's own reply is kept on the row", bool(_r.get("reply")))

reply({"target": "shell.exec", "field": "deny", "remove": [LOCAL], "add": [BROADER],
       "reason": "replace the localhost guard with one rule that covers both literals"})
_r2 = O.run("v1144-a")
check("C4 a covered replacement is still submitted", bool(_r2.get("proposal_id")), _r2)
if _r2.get("proposal_id"):
    check("C5 it waits on the operator",
          any(p.get("id") == _r2["proposal_id"] and p.get("status") == "pending"
              for p in I.list_proposals()), _r2["proposal_id"])

print("---")
passed = sum(RESULTS)
print("%d/%d PASS" % (passed, len(RESULTS)))
sys.exit(0 if passed == len(RESULTS) else 1)

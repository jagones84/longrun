#!/usr/bin/env python3
"""v1074 — the registry optimizer sees what was already tried, and prunes a repeat.

RRSI (arXiv:2609.24972, abstract) names two regularizers Longrun lacked on its LOCAL
optimizer: the proposer must be conditioned on the evolution history (so it does
not re-walk an explored trajectory), and a pruner removes changes that are "no
longer useful". `evolve/optimizer.py` read the trace and the LIVE policy, but not
one previous proposal: a denied delta could be re-proposed on every session,
filling the operator's inbox with the same rejected change.

Contract:
  H1 a delta's identity excludes `reason`/`confidence` and list order
  H2 the prompt gains an "already tried" section only when history exists
  H3 the section names status, target.field and the reason
  H4 `run` SKIPS an identical delta already pending/denied/approved
  H5 a DIFFERENT delta is still submitted through the normal pipeline
  H6 no history leaves the prompt byte-identical to the pre-change text

Deterministic: temp data/config dirs, the model is mocked, no network.
Run: python3 tests/acceptance/v1074_evolution_history_pruner.py
"""
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1074-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.makedirs(os.environ["LONGRUN_DATA_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.evolve import optimizer as O  # noqa: E402
from longrun.util import improve as I      # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


DELTA = {"target": "shell.exec", "field": "approval", "value": "required",
         "reason": "the row was too permissive", "confidence": "high"}
OTHER = {"target": "fs.read", "field": "approval", "value": "required",
         "reason": "reads asked too often", "confidence": "medium"}

# ---- H1: identity ------------------------------------------------------------
check("H1a reason/confidence are not part of the identity",
      O._delta_key(DELTA) == O._delta_key({**DELTA, "reason": "another prose",
                                           "confidence": "low"}))
check("H1b list order is not part of the identity",
      O._delta_key({"target": "shell.exec", "field": "deny",
                    "add": ["a", "b"]})
      == O._delta_key({"target": "shell.exec", "field": "deny",
                       "add": ["b", "a"]}))
check("H1c a different value is a different delta",
      O._delta_key(DELTA) != O._delta_key({**DELTA, "value": "auto"}))

# ---- H2/H3/H6: the prompt section -------------------------------------------
check("H2 empty history adds nothing", O._history_block([]) == "")
_hist = [{"id": "1-registry", "status": "denied", "delta": DELTA,
          "reason": "the row was too permissive"}]
_block = O._history_block(_hist)
check("H3 the section names status, target.field and reason",
      "[denied]" in _block and "shell.exec.approval" in _block
      and "the row was too permissive" in _block, _block)
_TRACE = {"tokens": 10, "steps": 2, "outcome": "ok", "model": "m"}
_p0 = O._build_analysis_prompt(_TRACE, {}, {}, {})
_p1 = O._build_analysis_prompt(_TRACE, {}, {}, {}, history=_hist)
check("H2b the section is present only with history",
      "Already proposed" not in _p0 and "Already proposed" in _p1)
check("H6 no history leaves the pre-change prompt intact",
      "do NOT propose an identical delta" not in _p0
      and "Reply with ONE JSON object" in _p0)

# ---- H4/H5: the pruner in run() ---------------------------------------------
O._read_trace = lambda sid: {"tokens": 10, "steps": 2, "outcome": "ok",
                             "model": "m"}
O._read_policy_hits = lambda: {}
O._read_job_cost = lambda jid: {}
O._read_feedback = lambda sid: {}

_seen_prompt = {"text": ""}


def fake_model(prompt):
    _seen_prompt["text"] = prompt
    return json.dumps(fake_model.delta)


fake_model.delta = DELTA

# Install a DENIED proposal carrying the same delta, through the real store.
_rec = I.propose("registry", "shell.exec.approval = required", reason="too permissive",
                 origin="optimizer", delta=DELTA)
I.decide(_rec["id"], "deny")
_n_before = len(I.list_proposals())

O._call_model = fake_model
_res = O.run("v1074-a")
check("H4a an identical denied delta is skipped",
      _res.get("skip") is True and "already proposed" in (_res.get("reason") or ""),
      _res.get("reason"))
check("H4b the skip names the earlier decision",
      "denied" in (_res.get("reason") or ""), _res.get("reason"))
check("H4c no duplicate proposal was written",
      len(I.list_proposals()) == _n_before,
      (len(I.list_proposals()), _n_before))
check("H4d the prompt it answered carried the history",
      "Already proposed" in _seen_prompt["text"])

# A different delta must still reach the inbox.
fake_model.delta = OTHER
_res2 = O.run("v1074-b")
check("H5 a different delta is still submitted",
      isinstance(_res2.get("proposal_id"), str) and _res2.get("proposal_id"),
      _res2)
check("H5b it is a real registry proposal",
      any(p.get("id") == _res2.get("proposal_id") and p.get("scope") == "registry"
          for p in I.list_proposals()))

shutil.rmtree(TMP, ignore_errors=True)
print("\n---\nv1074: %d/%d PASS" % (sum(RESULTS), len(RESULTS)))
raise SystemExit(0 if all(RESULTS) else 1)

#!/usr/bin/env python3
"""v1013 — the optimizer parses the model's registry delta and submits it (S1).

The optimizer asks the model (routing role `agent`) for ONE JSON object and submits
an APPLICABLE delta through the existing approvals pipeline (`improve.propose` with
scope `registry`). A reply it cannot parse, a `{"skip": true}` reply, or a delta the
registry owner would refuse all become a skip — never an unusable proposal.

Deterministic: the model call is stubbed, so no server and no network are used.
Run: python3 tests/acceptance/v1013_optimizer_delta.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1013-")
os.environ["LONGRUN_DATA_DIR"] = TMP
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_OPTIMIZER_LOG"] = os.path.join(TMP, "optimizer_runs.jsonl")
os.makedirs(os.environ["LONGRUN_RUNS_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.model import runmetrics      # noqa: E402
from longrun.evolve import optimizer       # noqa: E402
from longrun.util import improve           # noqa: E402
from longrun.tools import registry         # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def seed(sid, **kw):
    runmetrics.start(sid)
    runmetrics.finish(sid, tokens=kw.get("tokens", 500), steps=kw.get("steps", 3),
                      outcome=kw.get("outcome", "done"), model="test-model")


def proposals_on_disk():
    out = []
    d = improve.PROPOSAL_DIR
    if os.path.isdir(d):
        for fn in os.listdir(d):
            if fn.endswith(".json"):
                try:
                    with open(os.path.join(d, fn), encoding="utf-8") as f:
                        out.append(json.load(f))
                except (OSError, ValueError):
                    pass
    return out


seed("s-ok")

# ---- A) a valid delta is parsed and submitted as a registry proposal --------
_delta = {"target": "shell.exec", "field": "auto_approve",
          "add": ["^echo(\\s|$)"], "reason": "repeated friction on echo",
          "confidence": "medium"}
optimizer._call_model = lambda prompt, model=None: json.dumps(_delta)
r = optimizer.run("s-ok")
check("A1 run does not skip", r.get("skip") is not True, r)
check("A2 run carries the parsed delta", r.get("delta") == _delta, r.get("delta"))
check("A3 run carries a proposal id", bool(r.get("proposal_id")), r.get("proposal_id"))

props = [p for p in proposals_on_disk() if p.get("scope") == "registry"]
check("A4 a registry proposal landed on disk", len(props) == 1, len(props))
if props:
    rec = props[0]
    check("A5 proposal came from the optimizer", rec.get("origin") == "optimizer", rec.get("origin"))
    check("A6 proposal carries the exact delta", rec.get("delta") == _delta, rec.get("delta"))
    check("A7 proposal is pending (not auto-applied)", rec.get("status") == "pending", rec.get("status"))

# ---- B) a fenced / prose-wrapped reply is still parsed ----------------------
# v1074 (RRSI pruner): a second IDENTICAL delta is refused as "already proposed",
# so this case must carry a DIFFERENT change — it tests the parser, not duplicate
# submission. Same shape, different row.
_delta2 = {"target": "fs.write", "field": "approval", "value": "required",
           "reason": "writes asked too often", "confidence": "medium"}
seed("s-fenced")
optimizer._call_model = lambda prompt, model=None: (
    "Sure, here is the delta:\n```json\n" + json.dumps(_delta2) + "\n```\n")
r = optimizer.run("s-fenced")
check("B1 fenced reply parsed", r.get("delta") == _delta2, r.get("delta"))

# ---- C) a malformed reply becomes a skip -----------------------------------
seed("s-malformed")
optimizer._call_model = lambda prompt, model=None: "I could not find any issue."
r = optimizer.run("s-malformed")
check("C1 malformed reply skips", r.get("skip") is True, r)
check("C2 skip reason names the unparseable reply",
      r.get("reason") == "unparseable model reply", r.get("reason"))

# ---- D) the model's own skip is honoured -----------------------------------
seed("s-skip")
optimizer._call_model = lambda prompt, model=None: '{"skip": true, "reason": "clean run"}'
r = optimizer.run("s-skip")
check("D1 model skip is honoured", r.get("skip") is True, r)
check("D2 skip reason comes from the validator",
      "skip" in str(r.get("reason", "")).lower(), r.get("reason"))

# ---- E) a delta targeting an unknown row is refused ------------------------
seed("s-badtarget")
_bad = {"target": "not.a.real.tool", "field": "approval", "value": "auto", "reason": "x"}
optimizer._call_model = lambda prompt, model=None: json.dumps(_bad)
r = optimizer.run("s-badtarget")
check("E1 unknown target skips", r.get("skip") is True, r)
check("E2 reason names the unknown row",
      "not a known tool row" in str(r.get("reason", "")), r.get("reason"))

# ---- F) an invalid field/value is refused ----------------------------------
seed("s-badfield")
optimizer._call_model = lambda prompt, model=None: json.dumps(
    {"target": "shell", "field": "approval", "value": "perhaps", "reason": "x"})
r = optimizer.run("s-badfield")
check("F1 invalid approval value skips", r.get("skip") is True, r)
check("F2 reason names the allowed values",
      "auto" in str(r.get("reason", "")), r.get("reason"))

# ---- G) only applicable deltas reach the proposals store -------------------
final = [p for p in proposals_on_disk() if p.get("scope") == "registry"]
check("G1 the two valid deltas (plain + fenced) both landed", len(final) == 2, len(final))
check("G2 no proposal was written for a skip",
      all(p.get("delta", {}).get("target") in ("shell.exec", "fs.write")
          for p in final), len(final))

# ---- H) a LIST is changed with add/remove, never with a whole-list `value` --
# 2026-11-17: the optimizer's model rewrote `shell.exec.deny` from memory and
# proposed a one-entry list — one click from deleting seven hard-deny rules
# (LONGRUN_TOKEN, /proc/*/environ, mkfs, dd…). The owner validator now refuses a
# whole-list replacement and a `remove` that names a rule that does not exist.
_danger = {"target": "shell.exec", "field": "deny",
           "value": ["rm\\s+-rf\\s+/(\\s|$)"], "reason": "drop the .env grep block"}
_err = registry.delta_error(_danger)
check("H1 a whole-list `value` is refused with the reason", bool(_err)
      and "add" in _err and "remove" in _err, _err)

_bogus = {"target": "shell.exec", "field": "deny",
          "remove": ["THIS RULE DOES NOT EXIST"], "reason": "x"}
check("H2 a `remove` naming a rule that is not live is refused",
      "not in the live" in registry.delta_error(_bogus), registry.delta_error(_bogus))

_named = {"target": "shell.exec", "field": "deny",
          "remove": ["grep[^\\n]*\\.env"], "reason": "one named removal"}
check("H3 a named removal validates", registry.delta_error(_named) == "", registry.delta_error(_named))
_applied = registry.apply_delta(_named)
_live_deny = (registry.load_config(reload=True).get("tools", {})
              .get("shell.exec", {}) or {}).get("deny") or []
check("H4 it removes ONLY the named rule and keeps the token guards",
      _applied.get("ok") is True and "grep[^\\n]*\\.env" not in _live_deny
      and "LONGRUN_TOKEN" in _live_deny
      and any("environ" in p for p in _live_deny), _live_deny)

from longrun.tools import approvals as _appr_v  # noqa: E402
_view = _appr_v._improvement_view({
    "id": "legacy-danger", "scope": "registry", "status": "pending",
    "content": "replace the deny list", "reason": "x", "delta": _danger})
check("H5 the inbox BLOCKS a pending proposal whose delta cannot apply",
      _view.get("can_approve") is False and "cannot be applied" in (_view.get("blocked_reason") or ""),
      (_view.get("can_approve"), _view.get("blocked_reason")))
check("H6 the inbox carries the delta and the full text for the decision",
      _view.get("delta") == _danger and _view.get("detail") == "replace the deny list")

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)

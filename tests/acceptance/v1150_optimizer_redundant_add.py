#!/usr/bin/env python3
"""v1150 — an `add` that writes nothing is not a proposal (round 85).

Round 78 taught the gate to refute a `remove` that leaves an input unguarded
(`_uncovered_removal`); round 79 refuted a `remove` whose friction survives
(`_unchanged_friction`). Both look at removals. The other direction was unmeasured:
an `add` whose entry is ALREADY in the live list. `registry.apply_delta` computes
`live - remove + add` and skips an entry already present, so approving such a
delta writes no new guard while the inbox claims one.

Contract:
  A a genuinely new entry is not refuted
  B an entry already live is refuted, naming it
  C the same entry twice in one delta is refuted
  D an entry both removed and re-added is refuted
  E only list fields are judged (approval is not a list)
  F an unknown row stays the validator's refusal, not this gate's
  G a different-but-related rule is a REAL change (not refuted)
  H run() turns the duplicate into a skip and submits a real add
  I the prompt says an already-live add writes nothing

Deterministic: stubbed live list, no config, no model, no network.
Run: python3 tests/acceptance/v1150_optimizer_redundant_add.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1150-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_OPTIMIZER_LOG"] = os.path.join(TMP, "optimizer_runs.jsonl")
for _d in ("cfg", "data", "runs"):
    os.makedirs(os.path.join(TMP, _d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.evolve import optimizer as O       # noqa: E402

ENV = r"grep[^\n]*\.env"
HELD = r"\b(cat|head)[^\n]*data/heldout"
LIVE = [ENV, HELD]

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


import longrun.tools.registry as R          # noqa: E402


def _spec(name):
    return {"deny": list(LIVE)} if name in ("shell.exec", "shell") else {}


_orig_spec = R.tool_spec
R.tool_spec = _spec


def _d(**kw):
    base = {"target": "shell.exec", "field": "deny"}
    base.update(kw)
    return base


# ---- A) a new entry is a real change ---------------------------------------
check("A1 a new entry is not refuted",
      O._redundant_add(_d(add=[r"curl localhost"])) is None)
check("A2 no add at all is not this gate's business",
      O._redundant_add(_d(remove=[ENV])) is None)


# ---- B) an entry already live ----------------------------------------------
_b = O._redundant_add(_d(add=[ENV]))
check("B1 an already-live entry is refuted", bool(_b), _b)
check("B2 the refusal names the entry",
      bool(_b) and _b.get("pattern") == ENV, _b)
check("B3 the refusal says where it is live",
      bool(_b) and "already live" in (_b.get("why") or ""), _b)
check("B4 a second entry after a new one is still caught",
      bool(O._redundant_add(_d(add=[r"curl localhost", HELD]))), "mixed add")


# ---- C) the same entry twice ------------------------------------------------
_c = O._redundant_add(_d(add=[r"curl localhost", r"curl localhost"]))
check("C1 a doubled entry is refuted", bool(_c), _c)
check("C2 the reason is the duplicate, not 'already live'",
      bool(_c) and "listed twice" in (_c.get("why") or ""), _c)


# ---- D) removed and re-added ------------------------------------------------
_dd = O._redundant_add(_d(add=[ENV], remove=[ENV]))
check("D1 remove+add of the same entry is a no-op", bool(_dd), _dd)
check("D2 the reason names the re-add",
      bool(_dd) and "re-added" in (_dd.get("why") or ""), _dd)


# ---- E) only list fields -----------------------------------------------------
check("E1 an approval value is not judged by this gate",
      O._redundant_add(_d(field="approval", value="auto")) is None)


# ---- F) an unknown row is the validator's case -------------------------------
R.tool_spec = lambda name: {}
check("F1 an unknown target is not refuted here",
      O._redundant_add(_d(target="no.such.row", add=[ENV])) is None)
R.tool_spec = _spec


# ---- G) related is not identical ---------------------------------------------
check("G1 a broader rule with the same words is a real change",
      O._redundant_add(_d(add=[ENV + r"\.[a-z]+"])) is None)


# ---- H) run() skips the no-op and submits the real add -----------------------
O._read_trace = lambda sid: {"tokens": 10, "steps": 2, "outcome": "ok", "model": "m"}
O._read_policy_hits = lambda: {"firings": {}, "retired_rules": [], "never_fired": [],
                               "unknown_args": {}}
O._read_job_cost = lambda jid: {}
O._read_feedback = lambda sid: {}
O._evolution_history = lambda: []
SUBMITTED = []
_orig_submit = O._submit
O._submit = lambda delta, evidence, sid: (SUBMITTED.append(delta) or "pid")
try:
    O._call_model = lambda prompt, model=None: json.dumps(
        {"target": "shell.exec", "field": "deny", "add": [ENV],
         "reason": "re-assert the env guard", "confidence": "low"})
    _r = O.run("v1150-a")
    check("H1 the no-op add is a skip", _r.get("skip") is True and not SUBMITTED,
          _r.get("reason"))
    check("H2 the reason quotes the entry",
          repr(ENV) in (_r.get("reason") or ""), _r.get("reason"))

    O._call_model = lambda prompt, model=None: json.dumps(
        {"target": "shell.exec", "field": "deny", "add": [r"curl localhost"],
         "reason": "new guard", "confidence": "low"})
    _r2 = O.run("v1150-b")
    check("H3 a real add is still submitted",
          not _r2.get("skip") and len(SUBMITTED) == 1, _r2.get("reason"))
finally:
    O._submit = _orig_submit
    R.tool_spec = _orig_spec


# ---- I) the prompt tells the model -------------------------------------------
_p = O._build_analysis_prompt({"tokens": 1, "steps": 2}, {}, {}, {}, history=[])
check("I1 the prompt says an already-live add writes nothing",
      "already in the live list writes nothing" in _p)

print("---")
_passed = sum(RESULTS)
print("%d/%d PASS" % (_passed, len(RESULTS)))
sys.exit(0 if _passed == len(RESULTS) else 1)

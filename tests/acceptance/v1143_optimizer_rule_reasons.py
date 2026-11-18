#!/usr/bin/env python3
"""v1143 — the optimizer sees WHY each rule exists (round 78).

Round 77's first live proposal called two different guards "duplicates" and moved
to delete the `localhost` curl/wget rule — a rule the config explains in a `why`
("a tool call must not reach the control API around the gate…") that the prompt
never showed. The registry already carries `deny_why` and `deny_proof` beside the
pattern (rounds 63/68); this test pins that the optimizer prints them.

Contract:
  A the snapshot prints `deny why:` / `deny proof:` for the rules that carry them
  B it never invents a reason for a rule that has none
  C the prompt tells the model that resemblance is not redundancy
  D the live config's reasons reach the prompt, and the snapshot stays bounded

Deterministic: `tool_spec` is stubbed for A/B/D1, no network.
Run: python3 tests/acceptance/v1143_optimizer_rule_reasons.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.evolve import optimizer as O      # noqa: E402
from longrun.tools import registry as R        # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


HITS = {"firings": {"shell.exec:deny:LONGRUN_TOKEN": {"n": 4}},
        "retired_rules": [],
        "never_fired": ["shell.exec:deny:NEVER-RAN"],
        "never_fired_proof": {"shell.exec:deny:NEVER-RAN": "v1134_proof"},
        "unknown_args": {}}

_SPEC = {
    "approval": "auto",
    "deny": ["LONGRUN_TOKEN", "quiet-rule", "explained-but-long"],
    "always_ask": [], "auto_approve": [],
    "deny_why": {"LONGRUN_TOKEN": "the API bearer is the operator's credential",
                 "explained-but-long": "W" * 900,
                 "NOT-IN-DENY": "must never be printed"},
    "deny_proof": {"LONGRUN_TOKEN": "v1134_proof"},
}

_orig = R.tool_spec
R.tool_spec = lambda name, *a, **k: dict(_SPEC) if name == "shell.exec" else {}
try:
    SNAP = O._policy_snapshot(HITS)
finally:
    R.tool_spec = _orig

# ---- A) the reasons are printed ---------------------------------------------
check("A1 a rule's why is printed beside it",
      "deny why: LONGRUN_TOKEN — the API bearer is the operator's credential" in SNAP,
      SNAP[:400])
check("A2 a rule's proof is printed too",
      "deny proof: LONGRUN_TOKEN — v1134_proof" in SNAP, SNAP[:400])
check("A3 the exact deny list stays on the tool line (the copy source)",
      'deny=["LONGRUN_TOKEN", "quiet-rule", "explained-but-long"]' in SNAP, SNAP[:400])
check("A4 a long why is truncated",
      "W" * 200 in SNAP and "W" * 201 not in SNAP, len(SNAP))
check("A5 the never-fired rule names its proof",
      "NEVER-RAN — proved by v1134_proof" in O._build_analysis_prompt(
          {"tokens": 1, "steps": 1, "outcome": "ok", "model": "m"}, HITS, {}, {}),
      "NEVER-RAN")

# ---- B) no invented reasons --------------------------------------------------
check("B1 a rule with no why gets no why line",
      "deny why: quiet-rule" not in SNAP, SNAP[:400])
check("B2 a why for a pattern outside `deny` is never printed",
      "must never be printed" not in SNAP, SNAP[:400])

# ---- C) the instruction ------------------------------------------------------
_PROMPT = O._build_analysis_prompt({"tokens": 1, "steps": 1, "outcome": "ok",
                                    "model": "m"}, HITS, {}, {})
check("C1 the prompt says resemblance is not redundancy",
      "NOT redundant" in _PROMPT and "different" in _PROMPT, len(_PROMPT))
check("C2 a removal must say what still protects the case",
      "what still protects that case" in _PROMPT, len(_PROMPT))

# ---- D) the live config ------------------------------------------------------
_live = R.tool_spec("shell.exec") or {}
_why = _live.get("deny_why") or {}
check("D1 the shipped shell.exec rules carry reasons", bool(_why), sorted(_why))
_live_snap = O._policy_snapshot({"firings": {"shell.exec:deny:LONGRUN_TOKEN": {"n": 1}},
                                 "retired_rules": [], "never_fired": [],
                                 "unknown_args": {}})
check("D2 a shipped reason reaches the live snapshot",
      any(("deny why: %s — " % p) in _live_snap for p in _why), _live_snap[:300])
check("D3 the snapshot stays bounded", len(_live_snap) <= 9000, len(_live_snap))

print("---")
passed = sum(RESULTS)
print("%d/%d PASS" % (passed, len(RESULTS)))
sys.exit(0 if passed == len(RESULTS) else 1)

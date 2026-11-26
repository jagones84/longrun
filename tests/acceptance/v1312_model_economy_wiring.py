#!/usr/bin/env python3
"""v1312 — the model-economy wiring: a cascade that can resolve, and a run priced from its arms.

Two wires from round 173's subject, both fail-closed:

  A  `harness/model_cascade.plan()` resolves `small`/`large` from the operator's ROLE
     routing (`roles.subagent` / `roles.agent`) when the yaml aliases are empty, says
     WHICH source answered, refuses a dynamic `@role` ref, and stays disabled unless
     both tiers resolve — so the shipped config (enabled: false) changes nothing at
     runtime until the operator flips one flag;
  B  `harness/checks/model_budget.record_from_arms()` turns a benchmark run's arms
     (weak / strong / router, same tasks in order) into the claim record `audit()`
     prices — so a real run is priced automatically instead of by hand.

Deterministic: injected role refs, plain booleans. No model, no network, no server.
Run:  python3 tests/acceptance/v1312_model_economy_wiring.py
"""
import json
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from longrun.harness import model_cascade as mc            # noqa: E402
from longrun.harness.checks import model_budget as mb     # noqa: E402

FAILED = []
CHECKS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ((" — %s" % (detail,)) if detail else ""))
    CHECKS.append(name)
    if not ok:
        FAILED.append(name)


# ── A · the cascade resolves from role routing, fail-closed ─────────────────
_disabled = mc.plan({"enabled": False}, role_refs=lambda: ("local:q", "remote:g"))
check("A1 the shipped default is disabled even when both roles resolve",
      _disabled["enabled"] is False and _disabled["reason"] == "disabled", _disabled)
check("A2 a disabled plan still NAMES the resolved tiers and their source",
      _disabled["small"] == "local:q" and _disabled["large"] == "remote:g"
      and _disabled["source"] == "roles", _disabled)

_on = mc.plan({"enabled": True}, role_refs=lambda: ("local:q", "remote:g"))
check("A3 enabled + empty aliases resolves from roles and turns the cascade on",
      _on["enabled"] is True and _on["model"] == "local:q" and _on["source"] == "roles", _on)

_none = mc.plan({"enabled": True}, role_refs=lambda: ("", ""))
check("A4 enabled but neither tier resolvable stays OFF with a teaching reason",
      _none["enabled"] is False and "not configured" in _none["reason"]
      and _none["source"] == "none", _none)

_cfg = mc.plan({"enabled": True, "small": "a:x", "large": "b:y"},
               role_refs=lambda: ("local:q", "remote:g"))
check("A5 explicit yaml aliases win over the role routing",
      _cfg["enabled"] is True and _cfg["small"] == "a:x" and _cfg["source"] == "config", _cfg)

_dyn = mc.plan({"enabled": True}, role_refs=lambda: ("@chat", "remote:g"))
check("A6 a dynamic @role ref is refused (the cascade needs a concrete model)",
      _dyn["enabled"] is False, _dyn)

_esc = mc.decide({"current": "local:q", "failure_streak": 2}, _on)
check("A7 the live decision escalates to the resolved large tier on a failure streak",
      _esc["escalate"] is True and _esc["model"] == "remote:g" and _esc["reason"] == "failure-streak",
      _esc)
check("A8 a healthy state stays on the resolved small tier",
      mc.decide({"current": "local:q", "failure_streak": 0}, _on)["model"] == "local:q")

_shipped = mc.load()
check("A9 the shipped config is still off and unaliased (nothing changed at runtime)",
      _shipped.get("enabled") is False and not _shipped.get("small")
      and not _shipped.get("large"), {k: _shipped.get(k) for k in ("enabled", "small", "large")})
_agent = open(os.path.join(SRC, "longrun", "agent", "agent.py"), encoding="utf-8").read()
check("A10 the running loop still calls this exact seam",
      "_mc.plan(_mc.load(), interactive=True)" in _agent)
_same = mc.plan({"enabled": True}, role_refs=lambda: ("openrouter:x", "openrouter:x"))
check("A11 identical tiers are not a cascade (no saving) and stay off",
      _same["enabled"] is False and "identical" in _same["reason"], _same)
_partial = mc.plan({"enabled": True, "small": "a:x", "large": ""},
                   role_refs=lambda: ("local:q", "remote:g"))
check("A12 a half-set yaml is refused instead of mixing sources",
      _partial["enabled"] is False and "partial" in _partial["reason"], _partial)

# ── B · a benchmark run's arms become a priced claim ────────────────────────
_arms = {"weak": [True, False, True, False], "strong": [True, True, True, True],
         "router": [True, True, True, True], "quota": 0.5, "margin": 0.05}
_rec = mb.record_from_arms(_arms,
                           costs={"strong": [1, 1, 1, 1], "router": [0.2, 0.2, 0.2, 0.2]},
                           seeds=2)
check("B1 only-strong-correct is half the tasks", abs(_rec["osc"] - 0.5) < 1e-9, _rec)
check("B2 the oracle gap is the mean per-task headroom in points",
      abs(_rec["oracle_gap"] - 50.0) < 1e-9, _rec["oracle_gap"])
check("B3 the router's gain is its pass-rate delta in points",
      abs(_rec["claimed_gain"] - 50.0) < 1e-9, _rec["claimed_gain"])
check("B4 the captured share is gain over headroom", abs(_rec["capture"] - 1.0) < 1e-9, _rec)
check("B5 the spend is the router's cost over the all-strong cost",
      abs(_rec["spend"] - 0.2) < 1e-9, _rec["spend"])
check("B6 a consistent two-seed run prices clean",
      mb.audit(_rec)["verdict"] == "clean", mb.audit(_rec))
check("B7 one seed turns the same run into a finding",
      {f["kind"] for f in mb.audit(mb.record_from_arms(_arms, seeds=1))["findings"]}
      == {"single-seed"})
check("B8 mismatched arm lengths are refused, not silently truncated",
      mb.record_from_arms({"weak": [True, False], "strong": [True]})["reason"] == "mismatched-arms")
check("B9 a router that claims more than the oracle gap is flagged",
      "routing-beyond-oracle" in {f["kind"] for f in mb.audit(
          mb.record_from_arms({"weak": [False, False], "strong": [True, False],
                               "router": [True, True]}))["findings"]})

# ── C · the two live wires ──────────────────────────────────────────────────
_tmp = tempfile.mkdtemp(prefix="sf-v1312-")
_arms_file = os.path.join(_tmp, "arms.json")
json.dump({"weak": [True, False, True, False], "strong": [True, True, True, True],
           "router": [True, True, True, True], "seeds": 2, "quota": 0.5, "margin": 0.05},
          open(_arms_file, "w", encoding="utf-8"))
_run = subprocess.run([sys.executable, os.path.join(REPO, "forge.py"), "modelbudget",
                       "claim", _arms_file], capture_output=True, text=True, timeout=60)
check("C1 `modelbudget claim` prices a clean run and exits 0", _run.returncode == 0,
      (_run.stdout + _run.stderr)[-220:])
_bad = os.path.join(_tmp, "bad.json")
json.dump({"weak": [False, False], "strong": [True, False],
           "router": [True, True], "seeds": 1}, open(_bad, "w", encoding="utf-8"))
_run2 = subprocess.run([sys.executable, os.path.join(REPO, "forge.py"), "modelbudget",
                        "claim", _bad], capture_output=True, text=True, timeout=60)
check("C2 an over-claimed run exits 1", _run2.returncode == 1,
      (_run2.stdout + _run2.stderr)[-220:])
_cfg_file = os.path.join(_tmp, "cascade.json")
json.dump({}, open(_cfg_file, "w", encoding="utf-8"))
_run3 = subprocess.run([sys.executable, os.path.join(REPO, "forge.py"), "cascade", "plan",
                        _cfg_file], capture_output=True, text=True, timeout=60)
check("C3 `cascade plan` reports the source and stays disabled by default",
      _run3.returncode == 0 and '"enabled": false' in _run3.stdout
      and '"source"' in _run3.stdout, (_run3.stdout + _run3.stderr)[:300])

print()
if FAILED:
    print("FAILED %d/%d: %s" % (len(FAILED), len(CHECKS), ", ".join(FAILED)))
    sys.exit(1)
print("OK %d/%d" % (len(CHECKS), len(CHECKS)))

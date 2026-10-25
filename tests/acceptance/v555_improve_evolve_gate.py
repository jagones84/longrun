#!/usr/bin/env python3
"""v555 (staged, RED) — `improve ... evolve` must pass ONE approval gate.

M11 of the upgrade plan: `improve` is `approval: auto` in config/tools.yaml, so
`action=evolve` (mine + verify + archive a skill) runs without approval even
though the end-of-turn path asks. The fix is a subtool gate inside
`registry.classify()`.

This file lives in `.agent/docs/plans/staged-tests/` until the implementation lands, then it
moves to `tests/acceptance/` unchanged. Deterministic, no model, no network.

Run: python3 v555_improve_evolve_gate.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _repo(start):
    p = start
    while True:
        if os.path.isdir(os.path.join(p, "src", "longrun")):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            raise SystemExit("repository root not found from %s" % start)
        p = parent


REPO = _repo(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


gate = getattr(registry, "subtool_gate", None)
check("A1 registry.subtool_gate exists", callable(gate))

# ---- B: evolve requires approval, mine does not -----------------------------
if callable(gate):
    got = gate("improve", {"action": "evolve"})
    ok = isinstance(got, tuple) and len(got) == 2 and got[0] == "required"
    check("B1 improve+evolve -> required", ok, repr(got))
    reason = (got[1] if ok else "") or ""
    check("B2 the reason names the effect (a skill), not the tool",
          "skill" in reason.lower(), reason)

    check("B3 improve+mine -> no override", gate("improve", {"action": "mine"}) is None)
    check("B4 skills+apply is untouched", gate("skills", {"action": "apply"}) is None)
    check("B5 an unknown tool cannot crash the gate",
          gate("no.such.tool", {}) is None)
else:
    for name in ("B1 improve+evolve -> required", "B2 the reason names the effect (a skill), not the tool",
                 "B3 improve+mine -> no override", "B4 skills+apply is untouched",
                 "B5 an unknown tool cannot crash the gate"):
        check(name, False, "subtool_gate missing")

# ---- C: classify() must consult it after the global mode, before per-tool ----
try:
    with open(os.path.join(REPO, "src", "longrun", "tools", "registry.py"),
              encoding="utf-8") as f:
        _src = f.read()
except OSError as e:  # pragma: no cover
    _src = ""
    print("WARN cannot read registry.py: %s" % e)

# Scope the source locks to classify() itself: a bare find() hits the
# subtool_gate DEFINITION above it and passes vacuously.
_body = _src.split("def classify(", 1)[1] if "def classify(" in _src else ""
_use = _body.find("subtool_gate(tool, args)")
_mode = _body.find('ap.get("mode"')
_approval = _body.find('if spec["approval"] == "auto"')
check("C1 classify() calls subtool_gate", _use >= 0)
check("C2 the gate sits after the approvals.mode block", _mode >= 0 and _use > _mode,
      "mode=%d use=%d" % (_mode, _use))
check("C3 the gate sits before the per-tool 'auto' fast path",
      _use >= 0 and _approval >= 0 and _use < _approval,
      "use=%d approval=%d" % (_use, _approval))

# ---- D: the config stays 'auto' — the override lives in code ----------------
try:
    import yaml  # noqa: F401  (PyYAML is a runtime dependency)
    with open(os.path.join(REPO, "config", "tools.yaml"), encoding="utf-8") as f:
        _cfg = yaml.safe_load(f) or {}
    _imp = ((_cfg.get("tools") or {}).get("improve") or {})
    check("D1 improve is still approval: auto in config",
          str(_imp.get("approval", "")).lower() == "auto", repr(_imp))
except Exception as e:  # noqa: BLE001
    check("D1 improve is still approval: auto in config", False, str(e)[:120])

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)

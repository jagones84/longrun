#!/usr/bin/env python3
"""v1015 — an optimizer delta is adopted through the EXISTING approvals pipeline (S1).

An approved `registry` proposal changes exactly ONE row of the tool registry, in the
sparse overlay (data/tools.overlay.yaml) — `config/tools.yaml` is never touched. A
denied proposal leaves the registry byte-identical, and an invalid delta is refused
at apply time as well as at propose time.

Deterministic: temp data home, no server, no model.
Run: python3 tests/acceptance/v1015_registry_adoption.py
"""
import hashlib
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1015-")
os.environ["LONGRUN_DATA_DIR"] = TMP
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.makedirs(os.environ["LONGRUN_RUNS_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry        # noqa: E402
from longrun.util import improve           # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def digest(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return ""


def overlay_data():
    try:
        with open(registry.OVERLAY_YAML, encoding="utf-8") as f:
            body = f.read()
    except OSError:
        return None
    try:
        import yaml
        return yaml.safe_load(body) or {}
    except Exception:  # noqa: BLE001
        return json.loads(body)


BASE = registry.CONFIG_YAML
base_digest = digest(BASE)
check("A1 the registry base file exists", bool(base_digest), BASE)

DELTA = {"target": "shell.exec", "field": "auto_approve",
         "value": ["^optimizer-probe(\\s|$)"], "reason": "repeated friction on a probe"}
_PROBE = DELTA["value"][0]

# ---- B) a DENIED proposal leaves the registry byte-identical ---------------
p1 = improve.propose("registry", "shell.auto_approve += echo", reason="t",
                     origin="optimizer", delta=DELTA)
den = improve.decide(p1["id"], "deny")
check("B1 deny is accepted", den.get("ok") is True, den)
check("B2 the base file is byte-identical", digest(BASE) == base_digest)
check("B3 no overlay row was written", not os.path.exists(registry.OVERLAY_YAML),
      overlay_data())
live = registry.load_config().get("tools", {}).get("shell", {}) or {}
check("B4 the live row is unchanged",
      _PROBE not in (live.get("auto_approve") or []), live.get("auto_approve"))

# ---- C) an APPROVED proposal changes exactly ONE row -----------------------
p2 = improve.propose("registry", "shell.auto_approve += echo", reason="t",
                     origin="optimizer", delta=DELTA)
app = improve.decide(p2["id"], "approve")
check("C1 approve is accepted", app.get("ok") is True, app)
check("C2 the base file is STILL byte-identical", digest(BASE) == base_digest)

ov = overlay_data() or {}
tools_diff = ov.get("tools") or {}
check("C3 the overlay has exactly one changed row", list(tools_diff.keys()) == ["shell.exec"],
      list(tools_diff.keys()))
row = tools_diff.get("shell.exec") or {}
check("C4 that row changes exactly one field", list(row.keys()) == ["auto_approve"],
      list(row.keys()))
check("C5 the new value is the delta's value",
      row.get("auto_approve") == DELTA["value"], row.get("auto_approve"))

# ---- D) the merged live config reflects the change -------------------------
reg = registry.load_config(reload=True)
merged = (reg.get("tools", {}).get("shell.exec", {}) or {}).get("auto_approve") or []
check("D1 the merged registry carries the new value", _PROBE in merged, merged)

# ---- E) an INVALID delta is refused at apply time --------------------------
p3 = improve.propose("registry", "bogus", reason="t", origin="optimizer",
                     delta={"target": "not.a.tool", "field": "approval", "value": "auto"})
ref = improve.decide(p3["id"], "approve")
check("E1 an unknown target is refused", ref.get("ok") is False, ref)
check("E2 the refusal names the reason", "not a known tool row" in str(ref.get("error", "")),
      ref.get("error"))
ov2 = overlay_data() or {}
check("E3 a refused apply writes nothing new",
      (ov2.get("tools") or {}).keys() == {"shell.exec"}, list((ov2.get("tools") or {}).keys()))

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)

#!/usr/bin/env python3
"""v1017 — the FULL self-evolution loop closes (HarnessNet §3.1, §4.2).

Verifies the end-to-end HarnessNet self-evolution cycle in Longrun:

  session trace → optimizer proposal → approval → registry change → next session benefits

This test stitches together what v1013 (parse/submit) and v1015 (deny/approve) verify
separately, and adds the KEY assertion neither makes: after an approved registry change,
the NEXT session sees it — the loop is closed.

Deterministic: temp data home, model stubbed, no server, no network.
Run: python3 tests/acceptance/v1017_self_evolution_loop.py

Honest limits (what this test does NOT verify — the paper's training loop):
  - No batch → backward → validate → select-checkpoint cycle (Algorithm 5).
  - No validation set / success-rate measurement (the paper uses 42/80 held-out cases).
  - No Harness Gain or Training Gain metrics.
  - Model stubbed — the model's judgment is tested by v1013's parse/validate gates.
  - Single iteration — the paper runs multiple training iterations with checkpoint
    selection. These are architectural gaps (G4 deferred), not test deficiencies.
"""
import hashlib
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1017-")
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


BASE = registry.CONFIG_YAML
base_digest = digest(BASE)
_PROBE = "^selfevolve-probe(\\s|$)"
DELTA = {"target": "shell.exec", "field": "auto_approve",
         "value": [_PROBE], "reason": "repeated friction on the probe command",
         "confidence": "medium"}

# =========================================================================
# A — Setup
# =========================================================================
check("A1 the registry base file exists", bool(base_digest), BASE)
check("A2 the probe pattern is NOT in the shipped config",
      _PROBE not in str(registry.shipped_tool("shell", {}).get("auto_approve") or []),
      registry.shipped_tool("shell", {}).get("auto_approve"))

# =========================================================================
# B — Baseline: seed a session, read the registry BEFORE evolution
# =========================================================================
runmetrics.start("s-before")
runmetrics.finish("s-before", tokens=500, steps=3, outcome="done", code=0, model="test-model")

live_before = registry.load_config().get("tools", {}).get("shell.exec", {}) or {}
check("B1 the live registry does NOT contain the probe pattern",
      _PROBE not in (live_before.get("auto_approve") or []),
      live_before.get("auto_approve"))

# =========================================================================
# C — Optimizer proposes a delta
# =========================================================================
optimizer._call_model = lambda prompt, model=None: json.dumps(DELTA)
r = optimizer.run("s-before")
check("C1 run does not skip", r.get("skip") is not True, r)
check("C2 run carries the parsed delta", r.get("delta") == DELTA, r.get("delta"))
check("C3 run carries a proposal id", bool(r.get("proposal_id")), r.get("proposal_id"))

props = [p for p in proposals_on_disk() if p.get("scope") == "registry"]
check("C4 a registry proposal landed on disk", len(props) == 1, len(props))
if props:
    rec = props[0]
    check("C5 proposal came from the optimizer", rec.get("origin") == "optimizer", rec.get("origin"))
    check("C6 proposal carries the exact delta", rec.get("delta") == DELTA, rec.get("delta"))
    check("C7 proposal is pending (not auto-applied)", rec.get("status") == "pending", rec.get("status"))
    pid = rec["id"]

# =========================================================================
# D — Approve the delta
# =========================================================================
app = improve.decide(pid, "approve")
check("D1 approve is accepted", app.get("ok") is True, app)
check("D2 the base file is STILL byte-identical", digest(BASE) == base_digest)

ov = overlay_data() or {}
tools_diff = ov.get("tools") or {}
check("D3 the overlay has exactly one changed row", list(tools_diff.keys()) == ["shell.exec"],
      list(tools_diff.keys()))
row = tools_diff.get("shell.exec") or {}
check("D4 that row changes exactly one field", list(row.keys()) == ["auto_approve"],
      list(row.keys()))
check("D5 the new value is the delta's value",
      row.get("auto_approve") == DELTA["value"], row.get("auto_approve"))

reg = registry.load_config(reload=True)
merged = (reg.get("tools", {}).get("shell.exec", {}) or {}).get("auto_approve") or []
check("D6 the merged registry carries the probe pattern", _PROBE in merged, merged)

# =========================================================================
# E — Next session sees the change (THE KEY ASSERTION)
# =========================================================================
runmetrics.start("s-after")
runmetrics.finish("s-after", tokens=600, steps=4, outcome="done", code=0, model="test-model")

optimizer._call_model = lambda prompt, model=None: '{"skip": true, "reason": "clean run"}'
r2 = optimizer.run("s-after")
check("E1 the second run skips (model says clean)", r2.get("skip") is True, r2)
check("E2 the second run's evidence reflects the new session",
      (r2.get("evidence") or {}).get("tokens") == 600, r2.get("evidence"))
check("E3 the second run's evidence has the new step count",
      (r2.get("evidence") or {}).get("steps") == 4, r2.get("evidence"))

# The registry change PERSISTS across sessions.
reg2 = registry.load_config()
merged2 = (reg2.get("tools", {}).get("shell.exec", {}) or {}).get("auto_approve") or []
check("E4 the registry STILL carries the probe pattern after the second session",
      _PROBE in merged2, merged2)
check("E5 the overlay file still exists", os.path.exists(registry.OVERLAY_YAML),
      registry.OVERLAY_YAML)

# =========================================================================
# F — Deny leaves the registry unchanged
# =========================================================================
DELTA2 = {"target": "shell.exec", "field": "auto_approve",
          "value": ["^denied-pattern(\\s|$)"], "reason": "should not land"}
p2 = improve.propose("registry", "denied delta", reason="t", origin="optimizer", delta=DELTA2)
den = improve.decide(p2["id"], "deny")
check("F1 deny is accepted", den.get("ok") is True, den)

ov2 = overlay_data() or {}
check("F2 the overlay still has exactly one row (the approved one, not the denied one)",
      list((ov2.get("tools") or {}).keys()) == ["shell.exec"],
      list((ov2.get("tools") or {}).keys()))
check("F3 the denied pattern is NOT in the merged registry",
      "^denied-pattern" not in str(merged2), merged2)

# =========================================================================
# G — The complete data trail
# =========================================================================
try:
    with open(os.environ["LONGRUN_OPTIMIZER_LOG"], encoding="utf-8") as f:
        log_rows = [json.loads(line) for line in f if line.strip()]
except OSError:
    log_rows = []
check("G1 optimizer log has exactly 2 rows (one per session)", len(log_rows) == 2, len(log_rows))
check("G2 the first row carries a proposal_id",
      bool(log_rows[0].get("proposal", {}).get("proposal_id")), log_rows[0])
check("G3 the second row carries a skip",
      log_rows[1].get("proposal", {}).get("skip") is True, log_rows[1])

t1 = runmetrics.get("s-before")
t2 = runmetrics.get("s-after")
check("G4 s-before trace exists with correct outcome",
      t1 and t1.get("outcome") == "done", t1)
check("G5 s-after trace exists with correct outcome",
      t2 and t2.get("outcome") == "done", t2)

final_props = [p for p in proposals_on_disk() if p.get("scope") == "registry"]
check("G6 exactly 2 registry proposals exist (one approved, one denied)",
      len(final_props) == 2, len(final_props))
statuses = {p.get("status") for p in final_props}
check("G7 one is approved and one is denied",
      statuses == {"approved", "denied"}, statuses)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
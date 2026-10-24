#!/usr/bin/env python3
"""v589 (RED) — Paperclip-grade policy: rate_limit + argument_filters in classify().

Port of the Paperclip policy engine's two cheapest ideas (verified in KB round 3,
N3: `policyType: "rate_limit"` + `enforceRateLimit`, `argumentFiltersMatch`,
explicit-block priority, fail-closed invalid config):

- R1: a tool policy may carry `rate_limit: {max_calls, window_secs}`. Calls beyond
  the budget inside the window are denied (fail-closed), the counter resets when
  the window passes, and an invalid config denies instead of opening the gate.
- R2: a tool policy may carry `argument_filters: [{match: {k: v}, decision}]`.
  When ALL match pairs equal the call args, classify returns that decision
  (`required` or `denied`); otherwise the filters are silent.

Deterministic: no model, no network, no server, injectable clock.
Run: python3 tests/acceptance/v589_rate_limit_policy.py
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


# ---- A: the helpers exist -------------------------------------------------
check("A1 registry.rate_consume exists",
      callable(getattr(registry, "rate_consume", None)))
check("A2 registry.rate_reset exists",
      callable(getattr(registry, "rate_reset", None)))
check("A3 registry.argument_filter_hit exists",
      callable(getattr(registry, "argument_filter_hit", None)))

rc = getattr(registry, "rate_consume", None)
rr = getattr(registry, "rate_reset", None)
af = getattr(registry, "argument_filter_hit", None)

# ---- B: rate limiter behavior (injectable clock) ---------------------------
if callable(rc) and callable(rr):
    rr("t.tool")
    try:
        ok1 = rc("t.tool", 2, 60, now=1000.0) == "ok"
        ok2 = rc("t.tool", 2, 60, now=1001.0) == "ok"
        lim = rc("t.tool", 2, 60, now=1002.0)
        check("B1 two calls inside budget pass", ok1 and ok2)
        check("B2 third call is limited", isinstance(lim, str) and lim.startswith("limited"),
              repr(lim))
        check("B3 window expiry resets the budget",
              rc("t.tool", 2, 60, now=1070.0) == "ok")
        bad = rc("t.tool", 0, -5, now=1070.0)
        check("B4 invalid config fails closed",
              isinstance(bad, str) and bad.startswith("limited"), repr(bad))
        rr("t.tool")
        check("B5 reset clears the counter", rc("t.tool", 1, 60, now=1080.0) == "ok"
              and isinstance(rc("t.tool", 1, 60, now=1081.0), str))
    finally:
        rr("t.tool")
else:
    for n in ("B1", "B2", "B3", "B4", "B5"):
        check(n, False, "rate helpers missing")

# ---- C: argument filters ----------------------------------------------------
if callable(af):
    filters = [{"match": {"path": "/etc/passwd"}, "decision": "denied"},
               {"match": {"action": "evolve"}, "decision": "required"}]
    check("C1 full match denies",
          af(filters, {"path": "/etc/passwd", "extra": 1}) == "denied")
    check("C2 partial match is silent",
          af(filters, {"path": "/etc/passwdx"}) is None)
    check("C3 second filter matches on its key",
          af(filters, {"action": "evolve"}) == "required")
    check("C4 empty filters are silent", af([], {"a": 1}) is None)
    check("C5 unknown decision is ignored, not executed",
          af([{"match": {"a": 1}, "decision": "explode"}], {"a": 1}) is None)
else:
    for n in ("C1", "C2", "C3", "C4", "C5"):
        check(n, False, "argument_filter_hit missing")

# ---- D: classify() consults both, after mode, before auto -------------------
try:
    with open(os.path.join(REPO, "src", "longrun", "tools", "registry.py"),
              encoding="utf-8") as f:
        _src = f.read()
except OSError as e:
    _src = ""
    print("WARN cannot read registry.py: %s" % e)

_body = _src.split("def classify(", 1)[1] if "def classify(" in _src else ""
_use_rate = _body.find("rate_consume(")
_use_arg = _body.find("argument_filter_hit(")
_mode = _body.find('ap.get("mode"')
_approval = _body.find('if spec["approval"] == "auto"')
check("D1 classify() calls rate_consume", _use_rate >= 0)
check("D2 classify() calls argument_filter_hit", _use_arg >= 0)
check("D3 both sit after the approvals.mode block",
      _mode >= 0 and _use_rate > _mode and _use_arg > _mode)
check("D4 both sit before the per-tool 'auto' fast path",
      _use_rate < _approval and _use_arg < _approval and _approval >= 0)

# ---- E: end-to-end through classify with a patched spec ----------------------
try:
    real_spec = registry.tool_spec

    def _fake_spec(name, ext_snapshot=None, mtx_snapshot=None):
        s = real_spec(name, ext_snapshot, mtx_snapshot)
        if name == "fs.read" and isinstance(s, dict):
            s = dict(s, enabled=True, approval="auto", auto_approve=[],
                     deny=[], rate_limit={"max_calls": 2, "window_secs": 60},
                     argument_filters=[{"match": {"path": "/etc/passwd"},
                                        "decision": "required"}])
        return s

    registry.tool_spec = _fake_spec
    # The live checkout may run approvals.mode=full (explicit opt-out, which
    # correctly bypasses this gate). Pin normal mode so E tests the gate.
    real_cfg = registry.load_config
    registry.load_config = lambda reload=False: {"approvals": {"mode": "normal"},
                                                 "tools": {}}
    try:
        registry.rate_reset("fs.read")
        d1, _ = registry.classify("fs.read", {"path": "/tmp/a.txt"})
        d2, _ = registry.classify("fs.read", {"path": "/tmp/b.txt"})
        d3, r3 = registry.classify("fs.read", {"path": "/tmp/c.txt"})
        check("E1 two reads pass", d1 == "auto" and d2 == "auto",
              "%r %r" % (d1, d2))
        check("E2 third read inside window is denied by rate_limit",
              d3 == "denied" and "rate_limit" in r3, "%r %r" % (d3, r3))
        registry.rate_reset("fs.read")
        d4, r4 = registry.classify("fs.read", {"path": "/etc/passwd"})
        check("E3 argument filter forces approval even with budget left",
              d4 == "required" and "argument_filter" in r4, "%r %r" % (d4, r4))
    finally:
        registry.tool_spec = real_spec
        registry.load_config = real_cfg
        registry.rate_reset("fs.read")
except Exception as e:  # noqa: BLE001
    check("E1 two reads pass", False, "harness error: %s" % e)
    check("E2 third read inside window is denied by rate_limit", False, "skipped")
    check("E3 argument filter forces approval even with budget left", False, "skipped")

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)

#!/usr/bin/env python3
"""v565 — standing-permission taint (M2a, ClawMMU App. B).

A standing auto-approval (per-tool `approval: auto` or an `auto_approve`
pattern) applies ONLY when no untrusted content entered the proposing
context. Otherwise the exact call needs approval. `approvals.mode=full`
(the operator driving) still bypasses everything.

Deterministic, no live server, no network.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v565-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry       # noqa: E402

registry._external_tools = lambda: {}

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _classify(mode, *args, **kwargs):
    """classify() under a pinned approvals mode (the live install may set full)."""
    cfg = registry.load_config()
    ap = cfg.setdefault("approvals", {})
    saved = ap.get("mode", "normal")
    ap["mode"] = mode
    try:
        return registry.classify(*args, **kwargs)
    finally:
        ap["mode"] = saved


PURE = [{"role": "user", "content": "Goal: list processes"}]
TAINTED_OBS = PURE + [
    {"role": "assistant", "content": '{"action": "tool", "tool": "glob", "args": {}}'},
    {"role": "user", "content": "Observation (step 1/6):\nfile list here"},
]
TAINTED_MEM = [
    {"role": "system", "content": "Relevant memories from previous sessions:\n- (fact, 0.90) x"},
]
TAINTED_LEGACY = PURE + [
    {"role": "user", "content": "[harness] Observation for tool fs.read: ..."},
]

# ---- 1. pure helper probe -------------------------------------------------
check("1a no history is clean",
      registry.context_has_untrusted(None) is False
      and registry.context_has_untrusted([]) is False)
check("1b pure model+user turns are clean",
      registry.context_has_untrusted(PURE) is False
      and registry.context_has_untrusted(["just a string"]) is False)
check("1c loop observations taint",
      registry.context_has_untrusted(TAINTED_OBS) is True)
check("1d memory blocks taint",
      registry.context_has_untrusted(TAINTED_MEM) is True)
check("1e legacy harness observations taint",
      registry.context_has_untrusted(TAINTED_LEGACY) is True)

# ---- 2. auto_approve-pattern path ------------------------------------------
dec, reason = _classify("normal", "process", {"action": "list"}, hist=PURE)
check("2a pattern auto fires on a pure context",
      dec == "auto", "%s %s" % (dec, reason))
dec, reason = _classify("normal", "process", {"action": "list"}, hist=TAINTED_OBS)
check("2b tainted context suspends the standing pattern",
      dec == "required" and "standing auto-approval suspended" in reason,
      "%s %s" % (dec, reason))

# ---- 3. approval:auto spec path --------------------------------------------
dec, reason = _classify("normal", "glob", {"pattern": "*"}, hist=PURE)
check("3a spec auto fires on a pure context",
      dec == "auto", "%s %s" % (dec, reason))
dec, reason = _classify("normal", "glob", {"pattern": "*"}, hist=TAINTED_OBS)
check("3b tainted context suspends spec auto too",
      dec == "required" and "standing auto-approval suspended" in reason,
      "%s %s" % (dec, reason))

# ---- 4. owner-present bypass ------------------------------------------------
dec, reason = _classify("full", "process", {"action": "list"}, hist=TAINTED_OBS)
check("4a approvals.mode=full still bypasses under taint",
      dec == "auto", "%s %s" % (dec, reason))

# ---- 5. deny paths are untouched ---------------------------------------------
dec, reason = _classify("normal", "no.such.tool", {}, hist=TAINTED_OBS)
check("5a unknown tools stay denied (not merely required)",
      dec == "denied", "%s %s" % (dec, reason))

# ---- 6. the run loop actually passes its history to the gate -----------------
with open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"),
          encoding="utf-8") as f:
    _api = f.read()
check("6a loop + batch thread hist into tool_action",
      _api.count("hist=hist") >= 3, _api.count("hist=hist"))
check("6b tool_action and batch_action accept hist",
      "def tool_action(st, tool, args, on_event, workspace=None, hist=None)" in _api
      and "def batch_action(st, items, on_event, srv, workspace=None, hist=None)" in _api)

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)

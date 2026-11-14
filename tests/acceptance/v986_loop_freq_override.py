#!/usr/bin/env python3
"""v986 — the per-tool frequency override can actually fire.

`_ToolFreq.observe` kept only the last `window` calls and then counted inside
that window, so `count <= window` always. The shipped config sets
`loop_detection.per_tool.shell = {warn: 100, hard: 200}` against
`window: 50`: both shell thresholds were unreachable, and a run could loop on
`shell` forever with no "change strategy" nudge — the exact legitimate
high-frequency case the override exists for. 30 `fs.read` calls would trip it;
hundreds of shell calls would not.

Contract:
  A) shell warns at its configured threshold and hard-stops at its own;
  B) a normal tool keeps the global window/thresholds;
  C) interleaved types still do not trip each other (the design's point);
  D) a bad per-tool value falls back instead of crashing.

Deterministic: no model, no server, no network.

Run: python3 tests/acceptance/v986_loop_freq_override.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core.api_v02 import _ToolFreq  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


CFG = {"window": 50, "warn": 30, "hard": 50,
       "per_tool": {"shell": {"warn": 100, "hard": 200}}}

# --- A: the shell override fires ------------------------------------------
f = _ToolFreq(**CFG)
decisions = [f.observe("shell.exec")["decision"] for _ in range(200)]
check("A1 nothing fires before the warn threshold",
      all(d == "ok" for d in decisions[:99]), decisions[95:100])
check("A2 warn fires at 100", decisions[99] == "warn", decisions[99])
check("A3 hard_stop fires at 200", decisions[199] == "hard_stop", decisions[199])

# --- B: a normal tool keeps the global thresholds -------------------------
g = _ToolFreq(**CFG)
reads = [g.observe("fs.read")["decision"] for _ in range(50)]
check("B1 fs.read warns at the global 30", reads[29] == "warn", reads[28:31])
check("B2 fs.read hard-stops at the global 50", reads[49] == "hard_stop", reads[49])

# --- C: interleaving does not trip either ---------------------------------
h = _ToolFreq(**CFG)
out = []
for _ in range(60):
    out.append(h.observe("shell.exec")["decision"])
    out.append(h.observe("fs.read")["decision"])
check("C1 two interleaved types stay below their hard limits",
      "hard_stop" not in out, [d for d in out if d != "ok"][:5])

# --- D: a broken override falls back --------------------------------------
i = _ToolFreq(window=50, warn=30, hard=50,
              per_tool={"shell": {"warn": "x", "hard": None}})
check("D1 a bad value resolves to the global thresholds",
      i._limits("shell.exec") == (30, 50), i._limits("shell.exec"))

ok = sum(RESULTS)
print("\nv986: %d/%d PASS" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)

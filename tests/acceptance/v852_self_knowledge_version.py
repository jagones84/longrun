#!/usr/bin/env python3
"""v852 — one version, and the agent's self-knowledge says the TRUE one.

Live source (2026-11-07): the Head of Longrun Testing agent (A54) reported its
own identity as "Longrun v0.6" while `/api/self` and `self.info` answered
`1.0.0`. The system prompt's self-knowledge block had the number TYPED
(`agent.py: self_summary`), the API read `server.VERSION`, and the package root
had no version at all — three places, one of them stale.

Contract:
  A) the package root owns `__version__` and `server.VERSION` IS that value
     (a second literal anywhere is the defect this pins);
  B) `self_summary()` renders the SAME version, so the model is never told a
     number the service does not answer;
  C) the self-knowledge line in the source contains no typed version at all;
  D) the live `self.info` surface reports the same number (JAG-347 made it read
     `server.VERSION`; this ties the two surfaces to one string).

Deterministic: no server, no model, no network.
Run: python3 tests/acceptance/v852_self_knowledge_version.py
"""
import os
import re
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


TMP = tempfile.mkdtemp(prefix="v852_")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR",
           "ROLES_DIR", "DATA_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

import longrun  # noqa: E402
from longrun.core import server  # noqa: E402
from longrun.agent import agent as agent_mod  # noqa: E402
from longrun.tools import registry as REG  # noqa: E402

# Acceptance tests must never start MCP clients: the tool index is local here
# (same guard as v354), so `self.info` answers without spawning a stdio server.
REG._external_tools = lambda: {}

# ---- A: one truth for the number --------------------------------------------
check("A1 the package root defines __version__",
      bool(getattr(longrun, "__version__", "")), getattr(longrun, "__version__", "-"))
check("A2 server.VERSION IS the package version (not a second literal)",
      server.VERSION == longrun.__version__, "%r vs %r" % (server.VERSION,
                                                            longrun.__version__))
SERVER_SRC = read("src", "longrun", "core", "server.py")
check("A3 server.py assigns VERSION from longrun.__version__",
      re.search(r"^VERSION = _pkg_version$", SERVER_SRC, re.M)
      and "from longrun import __version__ as _pkg_version" in SERVER_SRC, "")

# ---- B: the prompt renders that same value ----------------------------------
summary = agent_mod.self_summary()
check("B1 the self-knowledge block names the LIVE version",
      ("Longrun v" + longrun.__version__) in summary,
      summary[:70])
check("B2 the stale v0.6 claim is gone from the prompt",
      "v0.6" not in summary, "")

# ---- C: no typed version in the self-knowledge line ------------------------
AGENT_SRC = read("src", "longrun", "agent", "agent.py")
check("C1 self_summary builds the version with a placeholder, never a literal",
      '"Self-knowledge: you are Longrun v%s' in AGENT_SRC
      and '"Self-knowledge: you are Longrun v0' not in AGENT_SRC, "")

# ---- D: the API surface agrees with the prompt -----------------------------
try:
    from longrun.tools.tools import _self
    info = _self({"action": "info"}, None)
    reported = str(info.get("version"))
except Exception as exc:  # noqa: BLE001 — report, never crash the gate
    info, reported = {}, "error: %s" % exc
check("D1 self.info reports the same version as the prompt",
      reported == longrun.__version__, "%r vs %r" % (reported, longrun.__version__))

print("\nv852: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)

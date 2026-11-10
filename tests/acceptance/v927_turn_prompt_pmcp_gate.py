#!/usr/bin/env python3
"""v927 — the PMCP block is advertised only when the gateway can actually answer.

R5 (2026-11-10, head-of-testing report): `system_prompt()` gated the block on the
mere PRESENCE of a client named `pmcp` in the MCP status. Two defects followed:

  A  the tracked config spells the client `PMCP` while the guard matched the
     lowercase literal, so the block was NEVER injected — verified live: gateway
     `connected=true, tools=26`, system prompt without "MCP gateway (PMCP)".
  B  a configured but disconnected (or tool-less) gateway would still advertise
     "~140 downstream MCP servers" — true only while the gateway answers.

The contract pinned here: the block is present iff a client whose name is `pmcp`
(case-insensitive) is ENABLED, CONNECTED and exposes at least one tool; any other
shape (absent, disabled, disconnected, zero tools, manager raising) yields the
base prompt unchanged.

Deterministic and offline: the MCP manager is a fake, no network, no model.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v927-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
for d in ("cfg", "sessions", "graphs", "data"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry  # noqa: E402

registry._external_tools = lambda: {}

from longrun.core import server as _srv  # noqa: E402,F401 — breaks the import cycle
from longrun.agent import agent as A  # noqa: E402
from longrun.interop import mcp_client as MC  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:400]) if detail and not ok else ""))


class _Mgr:
    def __init__(self, status):
        self._status = status

    def status(self):
        if isinstance(self._status, Exception):
            raise self._status
        return self._status


def _prompt(clients):
    MC.get_manager = lambda: _Mgr({"clients": clients})
    return A.system_prompt()


def _info(**kw):
    base = {"connected": True, "tools": 26, "enabled": True,
            "transport": "http", "error": None}
    base.update(kw)
    return base


BLOCK = "MCP gateway (PMCP)"

# ---- A: the tracked config spells it `PMCP` — the block must be present -------
p = _prompt({"PMCP": _info(), "time": _info(transport="stdio", tools=3)})
check("A1 uppercase key `PMCP` connected with tools -> block present",
      BLOCK in p and "catalog_search" in p, p[-200:])

# ---- B: a dead or empty gateway must not be advertised ------------------------
p = _prompt({"PMCP": _info(connected=False, tools=0)})
check("B1 disconnected gateway -> block absent",
      BLOCK not in p and "catalog_search" not in p, p[-200:])
p = _prompt({"PMCP": _info(tools=0)})
check("B2 connected but zero tools -> block absent", BLOCK not in p, p[-200:])
p = _prompt({"PMCP": _info(enabled=False)})
check("B3 disabled client -> block absent", BLOCK not in p, p[-200:])

# ---- C: name matching is case-insensitive, as the config is free-form --------
p = _prompt({"pmcp": _info()})
check("C1 lowercase key `pmcp` -> block present", BLOCK in p, p[-200:])
p = _prompt({"PmCp": _info()})
check("C2 mixed-case key `PmCp` -> block present", BLOCK in p, p[-200:])

# ---- D: no gateway / broken manager leaves the base prompt intact -----------
p = _prompt({"time": _info(transport="stdio", tools=3)})
check("D1 no pmcp client -> block absent", BLOCK not in p, p[-200:])
MC.get_manager = lambda: _Mgr(RuntimeError("manager exploded"))
p = A.system_prompt()
check("D2 a raising manager never breaks the prompt",
      BLOCK not in p and p.startswith(A.SYSTEM_PROMPT), p[-200:])
check("D3 the base prompt survives every shape", "You are Longrun" in p, p[:120])

print("=== v927: %d/%d PASS ===" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)

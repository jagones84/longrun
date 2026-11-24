#!/usr/bin/env python3
"""v1304 — `harness.graph`: the agent-facing read of the ONE topology census (round 170).

Round 169 shipped the census as a READ surface (the Orbit deck + `forge.py graph`); an
agent could not see it, while the tools that WRITE the topology (`agent.*`/`team.*`/
`job.*`) are architect-exclusive. This round closes the loop with ONE action on the
existing `harness` tool group (the same group `harness.status` lives in, v1238) — bounded,
read-only, and never the whole node set.

  A  the registry contract: `graph` is a declared `harness` action, reads no field, has
     one actionable guidance line, and opens no approval gate;
  B  the handler: `ok`, a bounded card, totals + a capped frontier + per-graph COUNTS —
     it never returns every node;
  C  read-only and fail-open: a second call is identical, and `harness.status` is intact;
  D  the report-only zone: `tools.py` reaches the harness ROOT, never `harness.checks`
     (ADR-0003, pinned by v1273).

Deterministic: temp stores, no model, no network, no server.
Run: python3 tests/acceptance/v1304_graph_harness_tool.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="lr-v1304-")
for key, name in (("LONGRUN_CONFIG_DIR", "cfg"), ("LONGRUN_SESSIONS_DIR", "sessions"),
                  ("LONGRUN_DATA_DIR", "data"), ("LONGRUN_DB", "events.db"),
                  ("LONGRUN_GRAPH_DIR", "graphs"), ("LONGRUN_JOBS", "jobs.json")):
    os.environ[key] = os.path.join(TMP, name)
    if not name.endswith(".json"):
        os.makedirs(os.environ[key], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry          # noqa: E402
from longrun.tools import tools as T        # noqa: E402

FAILED = []
CHECKS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ((" — %s" % (detail,)) if detail else ""))
    CHECKS.append(name)
    if not ok:
        FAILED.append(name)


# ── A · the registry contract ───────────────────────────────────────────────
SCHEMA = registry._LEGACY_SCHEMAS["harness"]
actions = SCHEMA["properties"]["action"].get("enum") or []
check("A1 graph is a declared harness action", "graph" in actions, actions)
check("A2 restart + status survive (no regression)",
      "restart" in actions and "status" in actions, actions)
check("A3 graph reads no field", registry._SUBTOOL_FIELDS["harness"].get("graph") == [],
      registry._SUBTOOL_FIELDS["harness"])
guide = registry._SUBTOOL_GUIDANCE.get("harness.graph") or ""
check("A4 it has one actionable guidance line", bool(guide), list(registry._SUBTOOL_GUIDANCE))
check("A5 the guidance is ONE action, not the namespace story", 0 < len(guide) < 400, len(guide))
check("A6 reading the topology opens no approval gate",
      registry.subtool_gate("harness.graph", {}) is None)

# ── B · the handler ─────────────────────────────────────────────────────────
out = T._harness({"action": "graph"}, None)
check("B1 the handler answers ok", out.get("ok") is True, out)
card = out.get("card")
check("B2 it carries a bounded card", isinstance(card, str) and len(card) <= 1400,
      len(card) if isinstance(card, str) else card)
check("B3 totals + a capped frontier + per-graph counts",
      isinstance(out.get("totals"), dict) and isinstance(out.get("frontier"), list)
      and isinstance(out.get("graphs"), list), sorted(out))
check("B4 it never returns the whole node set",
      "nodes" not in out and all(set(g) == {"name", "nodes", "edges"}
                                and isinstance(g["nodes"], int) and isinstance(g["edges"], int)
                                for g in (out.get("graphs") or [])), out.get("graphs"))
check("B5 an unknown action still errors", T._harness({"action": "nope"}, None).get("ok") is False)

# ── C · read-only and fail-open ─────────────────────────────────────────────
again = T._harness({"action": "graph"}, None)
check("C1 two reads agree (nothing is mutated by reading)",
      again.get("totals") == out.get("totals") and again.get("graphs") == out.get("graphs"))
st = T._harness({"action": "status"}, "no-such-session-1304")
check("C2 harness.status still answers (no regression)", isinstance(st, dict), str(st)[:120])

# ── D · the report-only zone (ADR-0003 / v1273) ─────────────────────────────
with open(os.path.join(REPO, "src", "longrun", "tools", "tools.py"), encoding="utf-8") as fh:
    src = fh.read()
check("D1 tools.py reaches the harness ROOT, never checks/",
      "from longrun.harness import graph_topology" in src
      and "from longrun.harness.checks" not in src
      and "longrun.harness.checks import" not in src)

print("\n%d/%d checks passed" % (len(CHECKS) - len(FAILED), len(CHECKS)))
if FAILED:
    print("FAILED: " + ", ".join(FAILED))
    sys.exit(1)

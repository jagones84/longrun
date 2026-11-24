#!/usr/bin/env python3
"""v1303 — graph engineering round 169: one typed-graph primitive, one census, one audit.

Topic: *graph engineering, the next step after harness engineering* (proposal
`.agent/docs/proposals/2026-11/2026-11-25_graph-engineering.md`, rows G1-G3).
Sources: the stored graph-engineering talk (Neo4j, `g_NgCLTibiM`); ToolGraph
(`S-2026-11-19-026`); intent graphs (`S-2026-11-19-171`); `S-2026-11-01-057`.

What this pins:

  A  the primitive — a `Graph` that carries TYPED edges (dep/contain/membership/
     handoff/feedback), and the four legacy `util/dag` functions UNCHANGED;
  B  the pure audit — `harness/checks/graph_topology.audit` names an orphan edge,
     an undeclared cycle and a dead blocker, and stays silent on a clean census
     (a declared dep+feedback loop is NOT a defect);
  C  the live census — `harness/graph_topology.build/census/card`; the card is
     bounded and silent when there is no graph, and the live read never raises;
  D  the wiring — `forge.py` owns the group (`graph report|audit`), and the
     report-only zone is respected (only forge imports `harness.checks`);
  E  G3 — the Orbit constellation carries the ONE census, and `orbit/api.py`
     reaches the harness ROOT, never `harness.checks` (v1273's invariant).

Deterministic: no model, no network, no server.
Run: python3 tests/acceptance/v1303_graph_topology.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "src")

# Isolate the data home BEFORE any app import (a census reads the live stores).
TMP = tempfile.mkdtemp(prefix="sf-v1303-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_JOBS"] = os.path.join(TMP, "jobs.json")
os.environ["LONGRUN_OPTIMIZER"] = "0"
if SRC not in sys.path:
    sys.path.insert(0, SRC)

FAILED = []
CHECKS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ((" — %s" % (detail,)) if detail else ""))
    CHECKS.append(name)
    if not ok:
        FAILED.append(name)


# ── A · the primitive ───────────────────────────────────────────────────────
from longrun.util import dag as G  # noqa: E402

check("A1 the edge kinds are declared",
      set(G.EDGE_KINDS) >= {"dep", "contain", "membership", "handoff", "feedback"}, G.EDGE_KINDS)
g = G.Graph()
for n in ("a", "b", "c"):
    g.add_node(n)
g.add_edge("a", "b")
g.add_edge("b", "c")
check("A2 waves over typed edges", g.waves() == [["a"], ["b"], ["c"]], g.waves())
check("A3 Graph.ready delegates to the module's own contract",
      g.ready({"a"}) == G.ready(g.nodes, g.deps(), {"a"}) and g.ready({"a"}) == ["a", "b"],
      g.ready({"a"}))
check("A4 a clean graph reports no cycle", g.has_cycle() is False)
check("A5 dep edges are counted", len(g.edges("dep")) == 2, g.edges("dep"))
g.add_edge("c", "a")                      # a dep cycle
check("A6 a dep cycle is REPORTED, not forbidden", g.has_cycle() is True)
cen = g.census()
check("A7 census format", cen["format"] == G.Graph.FORMAT, cen.get("format"))
check("A8 census carries nodes + typed edges",
      set(cen["nodes"]) == {"a", "b", "c"} and cen["counts"]["edges"]["dep"] == 3, cen["counts"])
check("A9 census reports the cycle", cen["cycle"] is True)
g2 = G.Graph()
g2.add_node("a"); g2.add_node("b"); g2.add_node("c")
g2.add_edge("a", "b"); g2.add_edge("b", "c")
g2.add_edge("c", "a", kind="feedback")
check("A10 a declared feedback loop is not a dep cycle", g2.has_cycle() is False, g2.edges())

# the four LEGACY functions are untouched (byte-identical behaviour)
check("A11 legacy waves", G.waves(["x", "y"], {"y": ["x"]}) == [["x"], ["y"]])
check("A12 legacy has_cycle", G.has_cycle(["x", "y"], {"x": ["y"], "y": ["x"]}) is True)
check("A13 legacy blockers_state", G.blockers_state(["b"], {"b": "failed"}) == (False, ["b"]))
check("A14 legacy ready (its own contract: pending minus unmet)",
      G.ready(["a", "b"], {"b": ["a"]}, {"a"}) == ["a", "b"])

# ── B · the pure audit ──────────────────────────────────────────────────────
from longrun.harness.checks import graph_topology as chk  # noqa: E402

check("B1 the checker declares its format", chk.FORMAT == "longrun-graph-topology/1", chk.FORMAT)
clean = {"format": chk.FORMAT,
         "graphs": {"taskgraph": {"nodes": ["a", "b"],
                                  "edges": [{"from": "a", "to": "b", "kind": "dep"}]}}}
out = chk.audit(clean)
check("B2 a clean census is clean",
      out["format"] == chk.FORMAT and out["findings"] == [] and out["verdict"] == "clean", out)

defects = {"format": chk.FORMAT, "graphs": {"subjobs": {
    "nodes": ["a", "b"],
    "edges": [{"from": "a", "to": "b", "kind": "dep"},
              {"from": "b", "to": "a", "kind": "dep"},   # undeclared cycle
              {"from": "a", "to": "zzz", "kind": "dep"}],  # orphan edge
    "statuses": {"a": "blocked", "b": "failed"},           # b failed -> a wedged
}}}
out = chk.audit(defects)
kinds = sorted({f["kind"] for f in out["findings"]})
check("B3 the orphan edge is named", "orphan-edge" in kinds, kinds)
check("B4 the undeclared cycle is named", "undeclared-cycle" in kinds, kinds)
check("B5 the dead blocker is named", "dead-blocker" in kinds, kinds)
check("B6 every finding carries a locator",
      all(f.get("graph") and f.get("detail") for f in out["findings"]), out["findings"])
check("B7 the verdict is defects", out["verdict"] == "defects", out["verdict"])

declared = {"format": chk.FORMAT, "graphs": {"g": {
    "nodes": ["a", "b"],
    "edges": [{"from": "a", "to": "b", "kind": "dep"},
              {"from": "b", "to": "a", "kind": "dep"},
              {"from": "b", "to": "a", "kind": "feedback"}],
}}}
out = chk.audit(declared)
check("B8 a declared dep+feedback loop is NOT a defect",
      out["verdict"] == "clean", out["findings"])

# ── C · the live census + card ──────────────────────────────────────────────
from longrun.harness import graph_topology as gt  # noqa: E402

check("C1 the live module declares its format", gt.FORMAT == "longrun-graph-topology/1", gt.FORMAT)
gg = G.Graph()
gg.add_node("a"); gg.add_node("b"); gg.add_edge("a", "b")
payload = gt.build({"taskgraph": gg})
check("C2 build aggregates one graph",
      payload["format"] == gt.FORMAT and "taskgraph" in payload["graphs"], payload.get("graphs"))
check("C3 totals are counted",
      payload["totals"]["nodes"] == 2 and payload["totals"]["edges"]["dep"] == 1, payload["totals"])
check("C4 the card is bounded", 0 < len(gt.card(payload)) <= gt.MAX_TEXT, len(gt.card(payload)))
check("C5 no graph, no card",
      gt.card({"format": gt.FORMAT, "graphs": {}}) == "" and gt.build({})["graphs"] == {})
live = gt.census()
check("C6 the live census reads the stores without raising",
      live["format"] == gt.FORMAT and "graphs" in live and "frontier" in live, list(live))
check("C7 the audit accepts the live census",
      chk.audit(live)["verdict"] in ("clean", "defects"), chk.audit(live)["verdict"])

# ── D · the wiring (read-only source pins) ──────────────────────────────────
with open(os.path.join(SRC, "longrun", "core", "forge.py"), encoding="utf-8") as fh:
    forge = fh.read()
check("D1 forge owns the group", 'add_parser("graph")' in forge)
check("D2 forge owns the adapter", "def cmd_graph(" in forge)
check("D3 the adapter is listed as a round checker", "Round 169" in forge)
with open(os.path.join(SRC, "longrun", "harness", "__init__.py"), encoding="utf-8") as fh:
    init = fh.read()
check("D4 harness/__init__ names the new module", "graph_topology" in init)

# ── E · G3 — the constellation carries the ONE census ───────────────────────
from longrun.orbit import api as oapi  # noqa: E402

c = oapi._constellation()
check("E1 the constellation carries the topology",
      isinstance(c.get("topology"), dict), list(c))
check("E2 it is the census format",
      c.get("topology", {}).get("format") == gt.FORMAT, c.get("topology", {}).get("format"))
with open(os.path.join(SRC, "longrun", "orbit", "api.py"), encoding="utf-8") as fh:
    apy = fh.read()
check("E3 orbit reaches the harness ROOT, not the report-only zone",
      "from longrun.harness import graph_topology" in apy
      and "from longrun.harness.checks" not in apy and "import harness.checks" not in apy)

print("\n%d/%d checks passed" % (len(CHECKS) - len(FAILED), len(CHECKS)))
if FAILED:
    print("FAILED: " + ", ".join(FAILED))
    sys.exit(1)

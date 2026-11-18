#!/usr/bin/env python3
"""Tool dependency graph — which call can feed which, compiled once.

Source: arXiv:2611.20569, "ToolGraph as a Q-Function for Test-Time Scaling of
Tool-Use Agents" (round 113). A deployed tool catalog has a dependency structure
that a general model does not reliably infer from descriptions alone. ToolGraph
compiles it into a directed, weighted graph: parameter matching and interventional
probes (run a chain with and without the proposed predecessor) propose edges whose
evidence is combined into an EDGE CONFIDENCE. The paper's warning is the part this
module keeps explicit: a value defined over tool TYPES cannot separate a correct
tool called with a wrong argument — so the feedback always names the required
arguments and the missing ones.

  * `build(catalog, transitions, probes)` -> nodes + scored edges; a catalog row
    that declares its effect contributes a typed edge from a writer of a resource
    to the readers of that same resource (round 121, arXiv:2610.35981 rows);
  * `rank(graph, after)` -> candidate next tools, by incoming confidence;
  * `feedback(graph, goal, candidate, state_types)` -> action-goal feedback that
    says what the candidate needs and what the state provides.

Pure: catalog and records in, graph and text out; nothing is executed.
"""
from __future__ import annotations

FORMAT = "longrun-tool-graph/1"
BASE_PARAM = 0.4
OBS_GAIN = 0.2
PROBE_GAIN = 0.4
FAIL_PENALTY = 0.2
EFFECT_GAIN = 0.3


def _spec(tool):
    tool = tool or {}
    ins = []
    for i in tool.get("inputs") or ():
        if isinstance(i, dict):
            ins.append({"name": str(i.get("name") or ""), "type": str(i.get("type") or "")})
        else:
            ins.append({"name": str(i), "type": ""})
    outs = []
    for o in tool.get("outputs") or ():
        if isinstance(o, dict):
            outs.append({"name": str(o.get("name") or ""), "type": str(o.get("type") or "")})
        else:
            outs.append({"name": str(o), "type": ""})
    return {"inputs": ins, "outputs": outs}


def _match(out, inp):
    if out["type"] and inp["type"] and out["type"] == inp["type"]:
        return "type:%s" % out["type"]
    if out["name"] and inp["name"] and out["name"] == inp["name"]:
        return "name:%s" % out["name"]
    return None


def build(catalog, transitions=None, probes=None):
    nodes = {}
    typed = {}
    for tool in catalog or ():
        if isinstance(tool, dict) and tool.get("name"):
            nodes[str(tool["name"])] = _spec(tool)
            if tool.get("writes") or tool.get("reads"):
                typed[str(tool["name"])] = {
                    "reads": [str(r) for r in tool.get("reads") or ()],
                    "writes": [str(r) for r in tool.get("writes") or ()],
                }
    edges = {}

    def _edge(a, b):
        return edges.setdefault((a, b), {"from": a, "to": b, "confidence": 0.0,
                                         "reasons": [], "observations": 0,
                                         "failures": 0})

    for a, sa in nodes.items():
        for b, sb in nodes.items():
            if a == b:
                continue
            for out in sa["outputs"]:
                for inp in sb["inputs"]:
                    why = _match(out, inp)
                    if why:
                        e = _edge(a, b)
                        e["reasons"].append("parameter-matching %s" % why)
                        e["confidence"] = min(1.0, e["confidence"] + BASE_PARAM)
                        break
                else:
                    continue
                break

    # Round 121: a declared writer precedes the readers of the resource it writes.
    # Two writers of the same resource are NOT chained — that is a conflict, and
    # the effect checker owns that verdict, not this graph.
    for a, ea in typed.items():
        for b, eb in typed.items():
            if a == b or not ea["writes"]:
                continue
            shared = sorted(set(ea["writes"]) & set(eb["reads"]))
            if not shared:
                continue
            e = _edge(a, b)
            e["reasons"].append("effect:%s" % ",".join(shared))
            e["confidence"] = min(1.0, e["confidence"] + EFFECT_GAIN)

    for t in transitions or ():
        if not isinstance(t, dict):
            continue
        a, b = str(t.get("from") or ""), str(t.get("to") or "")
        if a not in nodes or b not in nodes:
            continue
        e = _edge(a, b)
        if t.get("ok"):
            e["observations"] += 1
            e["reasons"].append("observed-success")
            e["confidence"] = min(1.0, e["confidence"] + OBS_GAIN)
        else:
            e["failures"] += 1
            e["reasons"].append("observed-failure")
            e["confidence"] = max(0.0, e["confidence"] - FAIL_PENALTY)

    for p in probes or ():
        if not isinstance(p, dict):
            continue
        a, b = str(p.get("from") or ""), str(p.get("to") or "")
        if a not in nodes or b not in nodes:
            continue
        e = _edge(a, b)
        if p.get("ok") and p.get("without_ok") is False:
            e["reasons"].append("interventional: needed")
            e["confidence"] = min(1.0, e["confidence"] + PROBE_GAIN)
        elif p.get("without_ok") is True:
            e["reasons"].append("interventional: not needed")
            e["confidence"] = max(0.0, e["confidence"] - PROBE_GAIN)

    return {"format": FORMAT, "nodes": nodes,
            "edges": sorted(edges.values(), key=lambda e: (-e["confidence"], e["from"], e["to"]))}


def rank(graph, after=None, min_confidence=0.0):
    """Candidate next tools by incoming confidence (optionally only after one tool)."""
    rows = [e for e in (graph or {}).get("edges") or ()
            if e["confidence"] >= float(min_confidence)
            and (after is None or e["from"] == str(after))]
    rows.sort(key=lambda e: (-e["confidence"], e["to"]))
    return [{"tool": e["to"], "confidence": round(e["confidence"], 3),
             "from": e["from"], "reasons": list(e["reasons"])} for e in rows]


def feedback(graph, goal, candidate, state_types=None):
    """Action-goal feedback that names the arguments, never only the types."""
    node = ((graph or {}).get("nodes") or {}).get(str(candidate))
    if not node:
        return {"format": FORMAT, "goal": str(goal), "candidate": str(candidate),
                "known": False, "text": "no catalog entry for %s" % candidate}
    have = {str(t) for t in (state_types or ())}
    missing = [i["name"] for i in node["inputs"]
               if not (i["type"] and i["type"] in have)]
    preds = rank(graph, after=None)
    preds = [p for p in preds if p["tool"] == str(candidate)][:3]
    lines = ["goal: %s -> %s" % (goal, candidate),
             "requires: %s" % (", ".join(i["name"] or "?" for i in node["inputs"]) or "no inputs")]
    if missing:
        lines.append("missing from state: %s" % ", ".join(missing))
    if preds:
        lines.append("likely predecessors: %s" % ", ".join(
            "%s(%.2f)" % (p["from"], p["confidence"]) for p in preds))
    lines.append("warning: type-level evidence cannot separate a right tool "
                 "called with a wrong argument; check the argument values")
    return {"format": FORMAT, "goal": str(goal), "candidate": str(candidate),
            "known": True, "missing_inputs": missing, "predecessors": preds,
            "text": "\n".join(lines)}

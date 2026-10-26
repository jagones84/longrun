"""v658 — a SCOPE is a view, not a filter over a second copy of the board.

Operator, on the Control deck: "se filtro per team mi appaiono altri team e blocchi
disconnessi in org chart e multi teams in AGENTS e stranger uncorrelated JOBS in
constellations with no arrow. this last may be a general problem not related to
filters — check codebase coherence for this all."

What was actually wrong (live evidence, scope T3 / Incident Response):

  A) AGENTS regrouped EVERY team over the already-scoped rows, so an agent in two
     teams was listed twice and the other teams' headers came back
     (live: groups ["T1","T2","T3"] with 17 rows for a 10-agent team).
  B) the org chart silently promoted to ROOT every agent whose manager sits in
     another team — a block floating with no manager and no edge
     (live: 10 nodes / 5 edges, 7 cut).
  C) the constellation payload carried SUBJOBS whose agent is outside the scope, so
     their "JN.j -> AX" pills were drawn with no arrow to any agent
     (live: 13 pills for T3, 10 pointing at A15/A20/A25-A28 — all in T1), and a job
     pill with no coordinator in scope and no visible subjob had no arrow at all.

The invariant: every object a scoped view renders must RESOLVE inside that scope.

Stdlib only, deterministic, no browser, no server, no network.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ORBIT = open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"),
             encoding="utf-8").read()
API = open(os.path.join(REPO, "src", "longrun", "orbit", "api.py"), encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name +
          ((" :: " + str(detail)) if (detail and not ok) else ""))


def _fn(src, name, next_name):
    i = src.find(name)
    j = src.find(next_name, i + len(name)) if i >= 0 else -1
    return src[i:j] if i >= 0 and j > i else ""


# ---- A. the scope owns the AGENTS grouping ----------------------------------
GROUPS = _fn(ORBIT, "  groupsOf(agents){", "  groupHtml(g){")
check("A1 only teams INSIDE the view are grouped",
      "const visible = id => scope === \"ALL\" || scope === id;" in GROUPS
      and "if (!visible(t.id)) return;" in GROUPS)
check("A2 an empty group survives only when it IS the scope",
      "const selected = id => scope === id;" in GROUPS
      and "if (ms.length || selected(t.id)) groups.push(" in GROUPS)
check("A3 the old always-true scope test is gone",
      # `scope === "ALL" || scope === id` used as `scoped(t.id)` made EVERY team
      # "in scope" under ALL and rendered every other team under a team scope.
      "const scoped = id => scope === \"ALL\" || scope === id;" not in GROUPS
      and "if (ms.length || scoped(t.id))" not in GROUPS)
check("A4 stray (unknown-team) buckets obey the same scope",
      "if (!visible(id) || this.teamById(id)) return;" in GROUPS)

# ---- B. the org chart states a cut instead of faking a root ------------------
RENDER = _fn(ORBIT, "    // v658 (operator: \"blocchi disconnessi in org chart\")",
             "const cw = Math.max(1, maxW + PAD)")
check("B1 the chart computes the cut set (manager outside the scope)",
      "const cutOf = {};" in RENDER
      and "!agents.some(x => x.id === a.reports_to)) cutOf[a.id] = a.reports_to;" in RENDER)
check("B2 the roots are seeded from the cut set, not re-derived inline",
      "agents.forEach(a => { if (cutOf[a.id]) roots.push(a); });" in RENDER)
check("B3 a cut leaves room for the stub",
      "const RTOP = Object.keys(cutOf).length ? PAD + 22 : PAD;" in RENDER
      and "place(r.a, r.m, PAD + bx, RTOP + byy);" in RENDER)
check("B4 the node carries the cut class and NAMES its manager",
      "'<div class=\"node' + (cut ? \" cut\" : \"\")" in ORBIT
      and "'<span class=\"ncut\">\\u21e1' + esc(cut) + '</span>'" in ORBIT
      and "outside this scope, so the chain is cut here" in ORBIT)
check("B5 the dashed stub is drawn by CSS from the same class",
      ".orgcanvas .node.cut::before{content:\"\";position:absolute;left:50%;top:-16px;width:0;height:16px;" in ORBIT
      and "border-left:1.4px dashed var(--line)" in ORBIT
      and ".orgcanvas .node .ncut{" in ORBIT)

# ---- C. no job pill without a relation --------------------------------------
ALL = _fn(ORBIT, "    let body = this._defs();\n    // v658: which jobs already carry a relation",
          "    agents.forEach(a => { const b = box[a.session];\n      body += '<rect class=\"cagent\"")
check("C1 the drawn relations are tracked once",
      "const linked = new Set();" in ALL
      and "linked.add(j.id);" in ALL and "linked.add(s.parent);" in ALL)
check("C2 a job with no visible relation is linked to its in-scope members",
      "jobs.forEach(j => { if (linked.has(j.id)) return;" in ALL
      and "(j.agents || []).filter(id => agents.some(a => a.id === id))" in ALL)
check("C3 the fallback cannot duplicate the subjob lane",
      # it runs ONLY after the coordinator/subjob/blocked_by edges added the id.
      ALL.index("linked.add(s.parent);") < ALL.index("if (linked.has(j.id)) return;"))

# ---- D. the payload never carries an out-of-scope subjob --------------------
check("D1 the server drops a subjob whose agent is out of scope",
      "if s.get(\"agent\") not in by_id:" in API
      and "asid = by_id.get(s.get(\"agent\")).get(\"session\")" in API)

_tmp = tempfile.mkdtemp(prefix="v658-")
os.environ["LONGRUN_DATA"] = os.path.join(_tmp, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "config")
sys.path.insert(0, os.path.join(REPO, "src"))
try:
    from longrun.orbit import api as orbit_api

    agents = [{"id": "A1", "session": "s1"}]
    jobs = [{"id": "J1", "subjobs": {
        "J1.1": {"id": "J1.1", "agent": "A1", "parent": "J1", "deps": []},
        "J1.2": {"id": "J1.2", "agent": "A2", "parent": "J1", "deps": []}}}]
    graphs = {"s1": {"nodes": [{"id": "1", "subjob": "J1.1", "plan": 1}]}}
    out = orbit_api._subjobs_of(agents, jobs, graphs)
    check("D2 a scoped payload keeps only the in-scope subjob",
          [s["id"] for s in out] == ["J1.1"], out)
    check("D3 the kept subjob still carries its todos",
          out and out[0]["todos"] == ["1"], out)
    all_out = orbit_api._subjobs_of(
        agents + [{"id": "A2", "session": "s2"}], jobs, graphs)
    check("D4 in ALL scope (every agent present) nothing is dropped",
          sorted(s["id"] for s in all_out) == ["J1.1", "J1.2"], all_out)
except Exception as e:  # noqa: BLE001 — a broken import is the failure
    check("D5 _subjobs_of imports and runs offline", False, repr(e))

print("\n---\nv658: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)

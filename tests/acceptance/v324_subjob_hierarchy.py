#!/usr/bin/env python3
"""v324 — the job/subjob/todo hierarchy is coherent (JAG-324).

User's fundamental model (states the links between the codebase's key objects):

    Job JN
      └─ Subjob JN.j         (one per agent, a DAG: subjobs have deps)
           ├─ agent AX        (= a session)
           └─ embraces a SUBSET of that agent's todos (TX)

A todo lives under an agent (session) AND under the subjob that produced it, so a
todo carries BOTH `jid` (its job) and `subjob` (the piece of work it belongs to).
The constellation maps all three levels.

Deterministic, no model. Run: python3 tests/acceptance/v324_subjob_hierarchy.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-324-")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.agent import agents  # noqa: E402
from longrun.orchestrate import jobs  # noqa: E402
from longrun.plan import taskgraph as tg  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


# ---- A: subjobs form a DAG (deps mirror the agent-level wave order) --------
subs = jobs.plan_subjobs("J7", ["A1", "A2", "A3"], "A1",
                         "- A2: gather\n- A3: draft", {"A3": ["A2"]})
check("A1 one subjob per delegable agent, coordinator excluded",
      set(subs) == {"J7.1", "J7.2"} and all(s["agent"] != "A1" for s in subs.values()),
      str(sorted(subs)))
check("A2 subjob ids are JN.j and bound to one agent",
      subs["J7.1"]["agent"] == "A2" and subs["J7.2"]["agent"] == "A3")
check("A3 subjob DEPENDENCIES mirror the agent deps (A3 waits on A2)",
      subs["J7.2"]["deps"] == ["J7.1"] and subs["J7.1"]["deps"] == [])

# ---- B: a todo carries its job AND its subjob -----------------------------
g = tg.ensure("sessA", session_id="sessA", goal="g")
g["jid"] = "J7"
g["subjob"] = "J7.1"
tg.save(g)
n1 = tg.add_node(tg.load("sessA"), "todo owned by subjob J7.1")
check("B1 a todo inherits (jid, subjob) from the graph it was created under",
      n1.get("jid") == "J7" and n1.get("subjob") == "J7.1", str({k: n1.get(k) for k in ("jid", "subjob")}))
g = tg.load("sessA")
g["subjob"] = None
tg.save(g)
n2 = tg.add_node(tg.load("sessA"), "loose todo (not in a subjob)")
check("B2 a todo with no active subjob is left untagged",
      n2.get("subjob") is None and n2.get("jid") == "J7")

# ---- C: a subjob embraces the subset of its agent's todos -----------------
# 2026-11-08: A1 is RESERVED for the harness supervisor; read the minted id.
W = agents.REGISTRY.designate("sessA", name="Worker A")["agent"]["id"]
made = jobs.JOBS.create("hierarchy goal", coordinator=W, agents=[W])
JID = made["job"]["id"]
SUB = JID + ".1"
jobs.JOBS._update(JID, lambda j: j.update({"subjobs": {
    SUB: {"id": SUB, "parent": JID, "agent": W, "deps": [], "status": "done"}}}))
# a todo this agent creates while working that subjob carries its id
g = tg.load("sessA")
g["jid"] = JID
g["subjob"] = SUB
tg.save(g)
n_in = tg.add_node(tg.load("sessA"), "todo owned by this subjob")
todos = jobs.JOBS.subjob_todos(JID)
check("C1 subjob_todos pivots the agent's todos onto the subjob",
      todos.get(SUB) == [n_in["id"]], str(todos))
check("C2 only the subjob's own todos are embraced (not the untagged ones)",
      n1["id"] not in (todos.get(SUB) or []) and n2["id"] not in (todos.get(SUB) or []))
det = jobs.JOBS.detail(JID)
check("C3 detail() attaches the todo subset to each subjob",
      det["subjobs"][SUB]["todos"] == [n_in["id"]], str(det["subjobs"]))
check("C4 the STORED job is untouched by the read-only enrichment",
      "todos" not in (jobs.JOBS.get(JID)["subjobs"][SUB]))

# ---- D: the constellation payload carries the subjob level ----------------
try:
    from longrun.orbit import api as oapi
    payload = oapi._subjobs_of(
        [{"id": "A1", "session": "s1"}],
        [{"id": "J1", "subjobs": {"J1.1": {"id": "J1.1", "agent": "A1", "deps": [],
                                           "status": "done"}}}],
        {"s1": {"nodes": [{"id": "n1", "subjob": "J1.1"}, {"id": "n2", "subjob": None}]}})
    check("D1 the constellation maps subjob -> agent + its todos",
          len(payload) == 1 and payload[0]["id"] == "J1.1"
          and payload[0]["agent"] == "A1" and payload[0]["todos"] == ["n1"], str(payload))
except Exception as e:  # noqa: BLE001
    check("D1 the constellation maps subjob -> agent + its todos", False, "import/run error: %s" % e)

# ---- E: wiring across the codebase ----------------------------------------
t = read("src", "longrun", "plan/taskgraph.py")
s = read("src", "longrun", "core/server.py") + read("src", "longrun", "core/httpapi.py")
j = read("src", "longrun", "orchestrate/jobs.py")
o = read("src", "longrun", "orbit", "web", "orbit.html")
i = read("webui", "index.html")
check("E1 add_node tags the node with the graph subjob", '"subjob": graph.get("subjob")' in t)
check("E2 a turn writes its subjob onto the graph",
      '_existing["subjob"] = subjob' in s and '_ex["subjob"] = None' in s)
check("E3 jobs exposes subjob deps + todo membership",
      '"deps": sdeps' in j and "def subjob_todos" in j and "def detail" in j)
check("E4 the constellation draws the subjob lane",
      "this.data.subjobs" in o and 'class="csub"' in o)
check("E5 the main app shows a subjob chip on a todo", "function _nodeSub(" in i and "n.subjob ?" in i)

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)


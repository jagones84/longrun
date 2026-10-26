#!/usr/bin/env python3
"""v677 — a parallel job's write paths are recorded and overlaps are reported (I-7).

Two teammates of one job run concurrently (different addresses dispatch in
parallel), so two sessions can write the same file: the second write may rest on
a stale read and one agent's work is lost silently, while both report success.
The ledger already recorded WHICH TOOL mutated a step, never WHICH FILE.

Covers:
  A) path extraction from a mutating call (`fs.write`/`fs.edit` only — `shell` is
     unattributable, a read is not a mutation)
  B) the ledger records paths beside the tool names, deduped, capped, deterministic
  C) the job-level derivation: a path written by >= 2 DIFFERENT agents of one job
     is reported; one agent writing a path twice is not; disjoint sets are silent
  D) `jobs.detail()` carries the same rows (one owner, no second truth)
  E) wiring: every ingress passes the args, the constellation payload carries the
     report, the job row renders it

Deterministic, no model, no network, no server.
Run: python3 tests/acceptance/v677_write_overlap.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-677-")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.agent import agents  # noqa: E402
from longrun.orchestrate import jobs as jobs_mod  # noqa: E402
from longrun.plan import taskgraph as tg  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


def touched(tool, args):
    """Call the extractor if it exists; None means 'not implemented yet'."""
    fn = getattr(tg, "touched_paths", None)
    if not callable(fn):
        return None
    try:
        return fn(tool, args)
    except Exception as e:  # noqa: BLE001
        return "raised: %s" % e


def record(graph, tool, node_id, paths):
    """Call note_mutation with paths; None means 'signature not extended yet'."""
    try:
        return tg.note_mutation(graph, tool, node_id, paths=paths)
    except TypeError as e:
        return "raised: %s" % e


# ---- A: which calls name a file -------------------------------------------
check("A1 fs.write names the file it wrote",
      touched("fs.write", {"path": "src/a.py", "content": "x"}) == ["src/a.py"],
      repr(touched("fs.write", {"path": "src/a.py", "content": "x"})))
check("A2 fs.edit names the file it edited",
      touched("fs.edit", {"path": "src/b.py", "search": "x", "replace": "y"}) == ["src/b.py"],
      repr(touched("fs.edit", {"path": "src/b.py", "search": "x", "replace": "y"})))
check("A3 shell is unattributable — no path is invented",
      touched("shell", {"cmd": "sed -i s/a/b/ src/c.py"}) == [],
      repr(touched("shell", {"cmd": "sed -i s/a/b/ src/c.py"})))
check("A4 a read is not a mutation",
      touched("fs.read", {"path": "src/d.py"}) == [],
      repr(touched("fs.read", {"path": "src/d.py"})))
check("A5 an empty/blank/missing path yields nothing",
      touched("fs.write", {"content": "x"}) == []
      and touched("fs.write", {"path": "   ", "content": "x"}) == [],
      repr(touched("fs.write", {"path": "   "})))

# ---- B: the ledger keeps the paths ---------------------------------------
g = tg.ensure("sessA", session_id="sessA", goal="g")
g["jid"] = "J9"
g["subjob"] = "J9.1"
tg.save(g)
n1 = tg.add_node(tg.load("sessA"), "write a file")
record(tg.load("sessA"), "fs.write", n1["id"], ["src/a.py", "src/a.py", "src/b.py"])
node = tg.find(tg.load("sessA"), n1["id"]) or {}
check("B1 the node carries the paths it wrote, deduped",
      node.get("paths") == ["src/a.py", "src/b.py"], str(node.get("paths")))
check("B2 the tool-name ledger still works beside it",
      (node.get("mutations") or []) == ["fs.write"], str(node.get("mutations")))

record(tg.load("sessA"), "fs.edit", n1["id"], ["src/p%02d.py" % i for i in range(13)])
node = tg.find(tg.load("sessA"), n1["id"]) or {}
cap = getattr(tg, "_PATH_CAP", None)
check("B3 the path list is capped like the tool list",
      isinstance(cap, int) and len(node.get("paths") or []) == cap,
      "cap=%r paths=%d" % (cap, len(node.get("paths") or [])))

before = list(tg.find(tg.load("sessA"), n1["id"]).get("paths") or [])
record(tg.load("sessA"), "fs.edit", n1["id"], before)
after = list(tg.find(tg.load("sessA"), n1["id"]).get("paths") or [])
check("B4 recording the same paths twice is idempotent", before == after, str(after))

# `note_mutation_current` must carry the paths on the SAME ingress the chat loop uses
g = tg.load("sessA")
g["nodes"] = []
tg.save(g)
n2 = tg.add_node(tg.load("sessA"), "current step", status="doing")
try:
    tg.note_mutation_current(tg.load("sessA"), "fs.write", paths=["src/cur.py"])
except TypeError as e:
    check("B5 note_mutation_current passes paths through", False, "signature: %s" % e)
node = tg.find(tg.load("sessA"), n2["id"]) or {}
check("B5 note_mutation_current passes paths through",
      node.get("paths") == ["src/cur.py"], str(node.get("paths")))

# ---- C: two agents of one job, one file ----------------------------------
agents.REGISTRY.designate("sessA", name="Worker A")
agents.REGISTRY.designate("sessB", name="Worker B")
ids = sorted(a["id"] for a in agents.REGISTRY.list()["agents"])
A1, A2 = ids[0], ids[1]
made = jobs_mod.JOBS.create("overlap goal", coordinator=A1, agents=[A1, A2])
JID = made["job"]["id"]


def arm(sess, agent, subjob, paths):
    """Give this agent's session a graph under the job and record its writes."""
    g = tg.ensure(sess, session_id=sess, goal="g")
    g["jid"] = JID
    g["subjob"] = subjob
    tg.save(g)
    n = tg.add_node(tg.load(sess), "edit under " + subjob)
    for p in paths:
        record(tg.load(sess), "fs.edit", n["id"], [p])
    return n["id"]


jobs_mod.JOBS._update(JID, lambda j: j.update({"subjobs": {
    JID + ".1": {"id": JID + ".1", "parent": JID, "agent": A1, "deps": [],
                 "status": "done"},
    JID + ".2": {"id": JID + ".2", "parent": JID, "agent": A2, "deps": [],
                 "status": "done"}}}))
arm("sessA", A1, JID + ".1", ["src/shared.py", "src/only_a.py"])
arm("sessB", A2, JID + ".2", ["src/shared.py", "src/only_b.py"])

fn = getattr(jobs_mod.JOBS, "write_overlaps", None)
rows = fn(JID) if callable(fn) else None
check("C1 a path written by two agents of one job is reported once",
      isinstance(rows, list) and len(rows) == 1
      and rows[0].get("path") == "src/shared.py"
      and sorted(rows[0].get("agents") or []) == sorted([A1, A2]),
      str(rows))
check("C2 the paths only one agent wrote are NOT conflicts",
      isinstance(rows, list) and len(rows) == 1,
      str(rows))

arm("sessB", A2, JID + ".2", ["src/only_b.py", "src/only_b.py"])
rows2 = fn(JID) if callable(fn) else None
check("C3 one agent writing a path twice is not a conflict",
      isinstance(rows2, list) and [r.get("path") for r in rows2] == ["src/shared.py"],
      str(rows2))

det = jobs_mod.JOBS.detail(JID) or {}
check("D1 detail() carries the same rows as the derivation",
      det.get("conflicts") == rows2, str(det.get("conflicts")))
check("D2 the STORED job is untouched by the read-only report",
      "conflicts" not in (jobs_mod.JOBS.get(JID) or {}))

# ---- E: wiring (the classes that bite: a kwarg the callers never pass) ----
agent_src = read("src", "longrun", "agent", "agent.py")
v2_src = read("src", "longrun", "core", "api_v02.py")
oapi_src = read("src", "longrun", "orbit", "api.py")
ohtml = read("src", "longrun", "orbit", "web", "orbit.html")
calls = [ln.strip() for ln in agent_src.splitlines()
         if "_note_chat_mutation(sess, tool" in ln and not ln.strip().startswith("def ")]
check("E1 every chat ingress passes the tool args",
      bool(calls) and all(", args)" in ln for ln in calls), str(calls))
check("E2 the v2 loop records the paths too",
      "touched_paths" in v2_src and "note_mutation_current" in v2_src)
check("E3 the constellation payload carries the report",
      "conflicts" in oapi_src and "write_overlaps" in oapi_src)
check("E4 the job row renders it", "conflicts" in ohtml)

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

#!/usr/bin/env python3
"""v669 — F1: a step that changed the environment is not closed on a text claim.

`requires_proof` existed but nothing set it for a model todo, so every step was
closeable with a sentence. This pins the mechanism added on top:

* a successful mutating tool marks the current step `mutated` (durable);
* `verifier.closeout` (default OFF, today's behaviour) verifies ONCE at closeout;
* green attaches an OBSERVED evidence entry, red keeps the step open;
* closeout on without a command refuses the close instead of faking a proof.

Deterministic, no live model, no network, no server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v669-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_PROJECTS_DIR"] = os.path.join(TMP, "projects")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.plan import taskgraph, verify      # noqa: E402
from longrun.tools import registry              # noqa: E402
from longrun.core import server                 # noqa: E402,F401 — breaks the import cycle
from longrun.agent import agent                 # noqa: E402

registry._external_tools = lambda: {}
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _cfg(**vals):
    """Pin the verifier block (the live install may differ)."""
    cfg = registry.load_config()
    ver = cfg.setdefault("verifier", {})
    saved = {k: ver.get(k) for k in vals}
    ver.update(vals)
    return saved


def _restore(saved):
    ver = registry.load_config().setdefault("verifier", {})
    for k, v in saved.items():
        if v is None:
            ver.pop(k, None)
        else:
            ver[k] = v


def _fresh(sid, label="step A"):
    g = taskgraph.ensure(sid, session_id=sid)
    node = taskgraph.add_node(g, label, status="doing")
    return g, node


def _green(**kw):
    return True, "ok"


def _red(**kw):
    return False, "boom"


# ---- A. the mutation marker ------------------------------------------------
g, node = _fresh("f1a")
marked = taskgraph.note_mutation(g, "fs.write", node["id"])
check("A1 a mutating tool marks its step",
      marked is not None and marked.get("mutated") is True, marked and marked.get("mutated"))
check("A2 the mark is durable and lists the tool",
      (taskgraph.load("f1a")["nodes"][0].get("mutations") or []) == ["fs.write"],
      taskgraph.load("f1a")["nodes"][0].get("mutations"))
taskgraph.note_mutation(g, "fs.write", node["id"])
check("A3 the same tool is recorded once",
      taskgraph.load("f1a")["nodes"][0].get("mutations") == ["fs.write"])
check("A4 an unknown step is a no-op, never a raise",
      taskgraph.note_mutation(g, "fs.write", "nope") is None)
check("A5 a text-only step does not need proof",
      taskgraph.needs_closeout_proof({"status": "doing"}) is False)
check("A6 a mutated step needs proof until an observed entry exists",
      taskgraph.needs_closeout_proof(marked) is True
      and taskgraph.needs_closeout_proof(
          {"mutated": True, "evidence": [{"text": "x", "observed": True}]}) is False)
_g7, _n7 = _fresh("f1a7")
check("A7 the current step is the one that gets marked",
      (taskgraph.note_mutation_current(_g7, "shell") or {}).get("id") == _n7["id"])

# ---- B. the closeout gate --------------------------------------------------
saved = _cfg(closeout=False, command="true")
try:
    ok, rep, obs = verify.closeout_gate(marked)
    check("B1 closeout OFF keeps today's behaviour",
          ok is True and rep.get("ran") is False and obs is False, rep)
finally:
    _restore(saved)

saved = _cfg(closeout=True, command="true")
try:
    ok, rep, obs = verify.closeout_gate({"status": "doing"})
    check("B2 a text-only step is not verified", ok and rep.get("ran") is False)

    ok, rep, obs = verify.closeout_gate(marked, check=_green)
    check("B3 green closeout closes with an observed proof",
          ok is True and obs is True and rep.get("green") is True, rep)
    ok, rep, obs = verify.closeout_gate(marked, check=_red)
    check("B4 red closeout keeps the step open",
          ok is False and obs is False and rep.get("green") is False, rep)
    ok, rep, obs = verify.closeout_gate(
        {"mutated": True, "evidence": [{"text": "x", "observed": True}]}, check=_red)
    check("B5 an observed proof is never re-checked", ok and rep.get("ran") is False)
finally:
    _restore(saved)

saved = _cfg(closeout=True, command="")
try:
    ok, rep, obs = verify.closeout_gate(marked, check=_green)
    check("B6 closeout without a command is fail-closed, not a fake proof",
          ok is False and obs is False and "command" in str(rep.get("error")), rep)
finally:
    _restore(saved)

# ---- C. the chat path uses it ----------------------------------------------
def _run(sid, label="step A"):
    sess = {"id": sid, "messages": [], "workspace": ""}
    g, node = _fresh(sid, label)
    taskgraph.note_mutation(g, "fs.write", node["id"])
    return sess, g, node


def _close(sess, node_id, evidence="wrote the file"):
    return agent._apply_chat_todo_updates(
        sess, {"steps": [{"id": node_id, "status": "done", "evidence": evidence}]},
        lambda *a, **k: None)


saved = _cfg(closeout=False, command="true")
try:
    sess, g, node = _run("f1c1")
    changed, errors = _close(sess, node["id"])
    check("C1 closeout OFF: the text claim still closes the step",
          changed == 1 and not errors, errors)
finally:
    _restore(saved)

saved = _cfg(closeout=True, command="true")
_orig = verify.run_check
try:
    verify.run_check = _green
    sess, g, node = _run("f1c2")
    changed, errors = _close(sess, node["id"])
    closed = taskgraph.find(taskgraph.load("f1c2"), node_id=node["id"]) or {}
    check("C2 green closeout closes the step",
          changed == 1 and not errors and closed.get("status") == "done", errors)
    check("C3 the close carries an OBSERVED evidence entry",
          any(e.get("observed") for e in (closed.get("evidence") or [])),
          closed.get("evidence"))

    verify.run_check = _red
    sess, g, node = _run("f1c3")
    changed, errors = _close(sess, node["id"])
    still = taskgraph.find(taskgraph.load("f1c3"), node_id=node["id"]) or {}
    check("C4 red closeout refuses the close and keeps the step open",
          changed == 0 and bool(errors) and still.get("status") == "doing",
          "%s %s" % (still.get("status"), errors))

    sess, g, node = _run("f1c4")
    plain = taskgraph.add_node(taskgraph.load("f1c4"), "step B", status="doing")
    changed, errors = _close(sess, plain["id"])
    check("C5 a text-only step is not blocked by an unrelated mutation",
          changed == 1 and not errors, errors)
finally:
    verify.run_check = _orig
    _restore(saved)

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)

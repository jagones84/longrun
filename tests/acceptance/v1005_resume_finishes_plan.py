#!/usr/bin/env python3
"""v1005 — a resumed turn keeps its ONE plan, and transient empty replies never end it.

Operator report (2026-11-14): the service was restarted mid-turn, the
`[Harness restart]` continuation was delivered to session `architect`, the agent
saved 4 steps and read the repo — and then the turn was force-closed with the
plan still open and the reply "Reply to continue". Why it died is in the durable
log:

  * the 3-step empty-reply cap counted LIFETIME empties, not consecutive ones:
    two reasoning-only replies, a successful 5-call batch, another batch and a
    third empty ended the turn with `stop_reason: empty_reply`;
  * the second `retry` injection was suppressed as a "byte-identical repeat", so
    the harness re-sent the request that had just produced nothing;
  * the graph had SPLIT in two: `architect.json` carried `key: <retired id>`
    (the identity migration renamed the file but not that field) and `save()`
    addresses the file by `key`, so every write went to a second file while every
    read by session id served the frozen one. The nudge after `todo.write` said
    "Task list saved (4 new step(s)) … OPEN (0): (none — the current plan is
    empty)" and the continuation loop saw no open step at all.

Locks:
  A  a graph is stored under ONE address: the file name is the authority and a
     later save can never resurrect the renamed alias;
  B  a rename-split pair converges on the NEWER copy and the stale duplicate
     moves to the recoverable trash; a different graph that merely shares the
     session is never adopted;
  C  three empty replies spread over real work do not close the turn, and every
     retry actually reaches the model;
  D  the identity migration rewrites the graph's `key` too.

Deterministic: temp data home, scripted model, stubbed tool gate, no server.
Run: python3 tests/acceptance/v1005_resume_finishes_plan.py
"""
import atexit
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1005-")
atexit.register(lambda: shutil.rmtree(TMP, ignore_errors=True))
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs_root")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_WORKSPACES_ROOT"] = os.path.join(TMP, "ws")
# enough real steps for the scripted turn; the iteration cap stays a backstop
os.environ["LONGRUN_CHAT_TOOL_STEPS"] = "12"
os.environ["LONGRUN_CHAT_TOOL_ITERS"] = "40"
for d in ("cfg", "sessions", "data", "edits", "runs", "ws",
          os.path.join("graphs_root", "graphs")):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry  # noqa: E402

registry._external_tools = lambda: {}

from longrun.core import server          # noqa: E402 — breaks the import cycle
from longrun.agent import agent as A     # noqa: E402
from longrun.plan import taskgraph as TG  # noqa: E402

GRAPHS = TG.GRAPH_DIR
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _write(name, obj):
    with open(os.path.join(GRAPHS, name), "w", encoding="utf-8") as fh:
        json.dump(obj, fh)


def _read(name):
    with open(os.path.join(GRAPHS, name), encoding="utf-8") as fh:
        return json.load(fh)


# ============================================================================
# A — one address per graph (the file name is the authority)
# ============================================================================
_write("sess-a.json", {"key": "retired-a", "run_id": "sess-a", "session_id": "sess-a",
                       "plan": 1, "plan_base": 1,
                       "nodes": [{"id": "n1", "plan": 1, "status": "done"}]})
_ga = TG.load("sess-a")
check("A1 load() returns the addressed graph with its OWN address",
      isinstance(_ga, dict) and _ga.get("key") == "sess-a" and _ga.get("run_id") == "sess-a",
      {k: (_ga or {}).get(k) for k in ("key", "run_id")})
check("A2 load() leaves the FILE alone (the boot heal must still see a split pair)",
      _read("sess-a.json").get("key") == "retired-a", _read("sess-a.json").get("key"))
TG.save(_ga)
check("A3 save() writes the file the graph was addressed by, with its address",
      _read("sess-a.json").get("key") == "sess-a"
      and not os.path.exists(os.path.join(GRAPHS, "retired-a.json")),
      sorted(os.listdir(GRAPHS)))

# ============================================================================
# B — a rename-split pair converges on the newer copy
# ============================================================================
_write("sess-b.json", {"key": "retired-b", "run_id": "sess-b", "session_id": "sess-b",
                       "plan": 1, "plan_base": 1, "updated": 10.0,
                       "nodes": [{"id": "n1", "plan": 1, "status": "done"}]})
_write("retired-b.json", {"key": "retired-b", "run_id": "sess-b", "session_id": "sess-b",
                          "plan": 1, "plan_base": 1, "updated": 20.0,
                          "nodes": [{"id": "n1", "plan": 1, "status": "done"},
                                    {"id": "n2", "plan": 1, "status": "todo"}]})
_rep = TG.heal_split_graphs()
_b = _read("sess-b.json")
check("B1 the split was reported", "sess-b" in _rep.get("healed", []), _rep)
check("B2 the NEWER copy wins (the open step survives)",
      _b.get("key") == "sess-b" and _b.get("run_id") == "sess-b"
      and [n.get("id") for n in _b.get("nodes") or []] == ["n1", "n2"],
      _b.get("nodes"))
check("B3 the stale duplicate is recoverable, not deleted",
      not os.path.exists(os.path.join(GRAPHS, "retired-b.json"))
      and os.path.exists(os.path.join(TMP, "data", "trash", "retired-b.json")),
      sorted(os.listdir(os.path.join(TMP, "data", "trash"))
             if os.path.isdir(os.path.join(TMP, "data", "trash")) else []))
check("B4 a second heal changes nothing (idempotent)",
      TG.heal_split_graphs().get("healed") == [], TG.heal_split_graphs())

# a run graph of the SAME session is a different graph: never adopted or trashed
_write("sess-c.json", {"key": "retired-c", "run_id": "sess-c", "session_id": "sess-c",
                       "plan": 1, "plan_base": 1, "updated": 10.0,
                       "nodes": [{"id": "n1", "plan": 1, "status": "todo"}]})
_write("retired-c.json", {"key": "retired-c", "run_id": "run-xyz", "session_id": "sess-c",
                          "plan": 1, "plan_base": 1, "updated": 20.0,
                          "nodes": [{"id": "r1", "plan": 1, "status": "done"}]})
TG.heal_split_graphs()
check("B5 a different graph sharing the session is left untouched",
      os.path.exists(os.path.join(GRAPHS, "retired-c.json"))
      and _read("sess-c.json").get("key") == "sess-c"
      and [n.get("id") for n in _read("sess-c.json").get("nodes") or []] == ["n1"],
      _read("sess-c.json").get("nodes"))

_api_src = open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"),
                encoding="utf-8").read()
check("B6 the boot heals the graphs BEFORE the orphan sweep looks at them",
      0 < _api_src.find("heal_split_graphs()") < _api_src.find("sweep_orphans()"),
      _api_src.find("heal_split_graphs()"))

# ============================================================================
# C — the resumed turn survives transient EMPTY replies
# ============================================================================
CALL = '{"action":"tool","tool":"shell","args":{"command":"echo hi"}}'
FINAL = "Done: the team is created, the read-back matches, nothing is left open."


def run_turn(sid, script, message="create the team and verify it"):
    state = {"n": 0}

    def fake_stream(msgs, model, role, on_delta, usage=None, cancel=None, **kw):
        text = script(state["n"])
        state["n"] += 1
        if text:
            on_delta("answer", text)
        return text, "", model

    def fake_gated(tool, args, **kw):
        return {"status": "executed",
                "observation": "[shell] exit=0 backend=stub sandboxed=False\nstdout: hi",
                "result": {"ok": True, "exit_code": 0, "stdout": "hi", "stderr": "",
                           "backend": "stub"}}

    events = []
    server.stream_with_fallback = fake_stream
    server.api_v02.gated_call = fake_gated
    server.chat_once({"id": sid, "messages": [], "workspace": ""}, message,
                     model="mock", on_delta=lambda c, t: None,
                     on_event=lambda kind, **d: events.append((kind, d)))
    return events


# tool, empty, tool, empty, tool, empty, answer — the measured 2026-11-14 shape
_SCRIPT = [CALL, "", CALL, "", CALL, "", FINAL]
ev = run_turn("v1005-sess", lambda n: _SCRIPT[min(n, len(_SCRIPT) - 1)])
kinds = [k for k, _d in ev]
errs = [d for k, d in ev if k == "chat.error"]
check("C1 three empty replies spread over real work do NOT close the turn",
      not errs, errs[:2])
check("C2 every real step still ran (3 tool calls)",
      kinds.count("tool.call") >= 3, kinds.count("tool.call"))
retries = [d for k, d in ev if k == "harness.inject" and d.get("inject_kind") == "retry"
           and "EMPTY" in (d.get("text") or "")]
check("C3 every empty reply earned a retry", len(retries) == 3,
      [d.get("text", "")[:40] for d in retries])
check("C4 no retry was dropped as a byte-identical repeat",
      retries and not any(d.get("repeat") for d in retries),
      [(d.get("repeat"), (d.get("text") or "")[:30]) for d in retries])
_sess = server.load_session("v1005-sess") or {}
_last = (_sess.get("messages") or [{}])[-1]
check("C5 the turn closed on the real answer",
      _last.get("role") == "assistant" and (FINAL[:20] in (_last.get("content") or "")),
      (_last.get("content") or "")[:80])

# the turn's own metrics must report the LOOP iterations: `_kg_rounds` read 0 on
# every turn that finished inside its first tool budget (114 of 149 measured).
from longrun.model import runmetrics as _rm  # noqa: E402
check("C5b run.metrics reports the real loop iterations, not keepgoing rounds",
      int((_rm.get("v1005-sess") or {}).get("iterations") or 0) >= 4,
      (_rm.get("v1005-sess") or {}).get("iterations"))

# a model that goes blank must NOT close a turn that still has work: the forced
# close forbids tools, which is exactly what the work needs (2026-11-14 reply:
# "the restart message forced a plain-text answer … tool calls were off the table")
_SID = "v1005-open-plan"
_write(_SID + ".json", {"key": _SID, "run_id": _SID, "session_id": _SID,
                        "plan": 1, "plan_base": 1, "updated": 1.0,
                        "nodes": [{"id": "n1", "plan": 1, "status": "todo",
                                   "label": "read the router"}]})
_SCRIPT2 = ["", "", "", CALL, FINAL]
ev2 = run_turn(_SID, lambda n: _SCRIPT2[min(n, len(_SCRIPT2) - 1)])
errs2 = [d for k, d in ev2 if k == "chat.error"]
parks = [d for k, d in ev2
         if k == "harness.inject" and d.get("inject_kind") == "continue"
         and "replies were empty" in (d.get("text") or "")]
check("C6 a 3rd empty does NOT close a turn that still has open steps", not errs2, errs2[:1])
check("C7 it parks with a CONTINUE naming the work, bounded to <= 2", 1 <= len(parks) <= 2,
      len(parks))
_sess2 = server.load_session(_SID) or {}
_last2 = (_sess2.get("messages") or [{}])[-1]
check("C8 the turn then works and answers",
      [k for k, _d in ev2].count("tool.call") >= 1
      and (FINAL[:20] in (_last2.get("content") or "")),
      (_last2.get("content") or "")[:80])

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)

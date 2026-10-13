#!/usr/bin/env python3
"""v451 — subagents are CONFIG-driven, manageable in the WebUI, with an explicit
context model (JAG-451).

Operator feedback: "subagents are in a config file? manageable by webui fully? i
can't even change their model / role / number; a subagents panel in Settings shall
contain all the info including the models, roles, number... does a subagent share
the parent's context?"

Contract pinned here:
  A) CONFIG — `config/subagents.yaml` holds `max_parallel` + named role briefs
     (model stays ONE source of truth in routing.yaml roles.subagent).
  B) SPAWN  — honours a `role` brief (prepended) and REFUSES past `max_parallel`;
     the subagent goal is the ONLY thing it sees (context is ISOLATED).
  C) API    — GET/POST /api/subagents exist.
  D) UI     — Settings ▸ Subagents panel exists (model, limits, roles) + the prompt
     tells the parent the child has an isolated context.

Deterministic, no model, no server. Run: python3 tests/acceptance/v451_subagents_panel.py
"""
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-451-")
os.environ["LONGRUN_SUBAGENTS_CFG"] = os.path.join(TMP, "subagents.yaml")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.makedirs(os.environ["LONGRUN_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.agent import subagent as SA           # noqa: E402
from longrun.core import api_v02 as A2             # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A) config load/save round-trip + role brief ----------------------------
cfg = {"version": "1", "max_parallel": 2,
       "roles": {"coder": "Implement a small self-contained change.",
                 "researcher": "Summarise sources; do not modify files."}}
SA.save_cfg(cfg)
SA.load_cfg(reload=True)
check("A1 the config round-trips (max_parallel persisted)",
      SA.load_cfg().get("max_parallel") == 2, SA.load_cfg().get("max_parallel"))
check("A2 role_brief returns the named brief",
      "self-contained" in SA.role_brief("coder"), SA.role_brief("coder"))
check("A3 an unknown role yields an empty brief", SA.role_brief("nope") == "")
check("A4 the repo ships config/subagents.yaml",
      os.path.exists(os.path.join(REPO, "config", "subagents.yaml")))


# ---- B) spawn honours the role + the parallel cap --------------------------
_cap = {}


def _fake_new_run(goal, model=None, max_steps=6, script=None):
    _cap["goal"] = goal
    _cap["model"] = model
    return type("_St", (), {
        "id": "run_test", "status": "running",
        "model": model, "parent_run_id": None,
    })()


_orig_new_run = A2.new_run
_orig_run = A2.agent_run_v2
A2.new_run = _fake_new_run
A2.agent_run_v2 = lambda *a, **k: {"status": "done", "trace": [], "summary": "ok"}
try:
    SA.load_cfg(reload=True)
    cfg["max_parallel"] = 1                       # cap = 1, one already running
    SA.save_cfg(cfg)
    SA.load_cfg(reload=True)
    SA._running.clear()
    SA._running["sub_x"] = {"id": "sub_x"}        # one already running
    refused = SA.spawn("do X", max_steps=2, role="coder", depth=0, on_event=lambda *a, **k: None)
    check("B1 the parallel cap refuses a spawn at the limit",
          refused.get("subagent_id") is None and "max parallel" in (refused.get("error") or ""),
          refused.get("error"))

    cfg["max_parallel"] = 0                       # no cap
    SA.save_cfg(cfg)
    SA.load_cfg(reload=True)
    SA._running.clear()
    sp = SA.spawn("do X", max_steps=2, role="coder", depth=0, on_event=lambda *a, **k: None)
    time.sleep(0.3)
    check("B2 a spawn under the cap starts", bool(sp.get("subagent_id")), sp)
    check("B3 the role brief is prepended to the goal the child receives",
          "[role: coder]" in (_cap.get("goal") or ""), _cap.get("goal"))
    SA.collect(sp.get("subagent_id"), timeout=2)
finally:
    A2.new_run = _orig_new_run
    A2.agent_run_v2 = _orig_run
    SA._running.clear()


# ---- C) API wiring ----------------------------------------------------------
api_src = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"), encoding="utf-8").read()
check("C1 GET /api/subagents is routed", 'if path == "/api/subagents":' in api_src)
check("C2 the GET exposes model/depth/parallel/roles/context",
      '"max_parallel"' in api_src and '"context": "isolated"' in api_src
      and '"roles"' in api_src)
check("C3 POST /api/subagents persists (roles + model via routing)",
      "_sub.save_cfg(cfg)" in api_src and '"subagent": upd' in api_src)
check("C4 both subagents handlers lazy-load routing before touching _ROUTING",
      api_src.count('_lazy(\'routing\')') >= 2)

# ---- D) UI panel + parent-facing context clarity ---------------------------
idx = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
agent_src = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"), encoding="utf-8").read()
check("D1 Settings has a Subagents category",
      '["subagents", "Subagents"]' in idx and 'data-cat="subagents"' in idx)
check("D2 the panel has model, depth, parallel + roles controls",
      'id="subModel"' in idx and 'id="subDepth"' in idx and 'id="subParallel"' in idx
      and 'id="subRolesBox"' in idx)
check("D3 the panel loads/saves /api/subagents",
      "loadSubagents" in idx and "saveSubagents" in idx and '"/api/subagents"' in idx)
check("D4 the panel states the context is ISOLATED",
      "does NOT share the parent's context" in idx or "not share the parent" in idx.lower())
check("D5 the parent prompt says the child context is isolated",
      "ISOLATED context" in agent_src and "NEVER your conversation" in agent_src)

print("---")
ok = sum(results)
print("\nv451: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

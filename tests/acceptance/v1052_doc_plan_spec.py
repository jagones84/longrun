#!/usr/bin/env python3
"""v1052 (RED) — /plan and /spec write documents and use the existing plan gate.

`/plan` is NOT the todo list: the task graph is never touched. The document is a
plain markdown file under `<workspace>/.longrun/documents/`, recorded on the
session's existing `plan` object, and `stores.set_plan_mode` locks mutating tools
until the operator approves. `/spec` writes the TRAE-style three-file set.

Deterministic: temp dirs, a stubbed planner, no model, no network.
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="lr-v1052-")
for _d in ("cfg", "sessions", "data", "projects", "graphs"):
    os.makedirs(os.path.join(TMP, _d), exist_ok=True)
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_PROJECTS_DIR"] = os.path.join(TMP, "projects")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_WORKSPACE"] = os.path.join(TMP, "ws")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.makedirs(os.environ["LONGRUN_WORKSPACE"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import stores  # noqa: E402
from longrun.plan import docs  # noqa: E402
from longrun.plan import taskgraph  # noqa: E402
from longrun.util import fswrite, paths  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


def session(ws):
    s = stores.get_or_create_session(None, title="v1052", workspace=ws)
    return s["id"]


PLAN_MD = """# Plan — add a health endpoint

Status: proposed · Created: 2026-11-16

## Request
add a health endpoint

## Grounding
- ASSUMPTION: the API is the local Longrun HTTP server.

## Approach
Add one read-only route and one test.

## Steps
1. Add GET /health — evidence of done: curl returns 200.
2. Add the acceptance test — evidence of done: vNNN green.

## Verification
- python3 tests/acceptance/vNNN.py
- live: curl http://127.0.0.1:8790/health

## Risks & rollback
- revert the route and the test.
"""

SPEC_MD = """# Health endpoint — Spec

## Why
Operators need a liveness probe.
## What Changes
Add GET /health.
## Impact
- src/longrun/core, tests/acceptance.
## ADDED Requirements
### Requirement: liveness probe
The system SHALL answer GET /health with 200.
#### Scenario: healthy
- **WHEN** GET /health
- **THEN** 200 and `{ok:true}`
## REMOVED Requirements
## Open Questions
"""

TASKS_MD = """# Tasks — health endpoint

The route first, then its proof.

1. add the route
   - [ ] Subtask 1.1: add the handler
   - [ ] Subtask 1.2: test vNNN
2. verify live
# Task Dependencies
- Task 2 depends on Task 1 (the route must exist).
"""

CHECK_MD = """# Checklist — health endpoint

## Route
- [ ] GET /health returns 200
- [ ] python3 tests/acceptance/vNNN.py is green

## Final verification
- [ ] Deterministic gate
- [ ] Service restart + live curl
"""

_orig_plan = docs._generate_plan_doc
_orig_spec = docs._generate_spec_docs


def stub_plan(md=PLAN_MD):
    docs._generate_plan_doc = lambda goal, model=None, context="": (md, "fake-model")


def stub_spec(docs_map=None):
    payload = docs_map or {"spec.md": SPEC_MD, "tasks.md": TASKS_MD, "checklist.md": CHECK_MD}
    docs._generate_spec_docs = lambda goal, model=None, context="": (payload, "fake-model")


# ---------------------------------------------------------------- A: /plan
ws = os.path.join(TMP, "ws-plan")
os.makedirs(ws, exist_ok=True)
sid = session(ws)
stub_plan()
r = docs.create_plan(sid, "add a health endpoint")
sess = stores.load_session(sid)
plan = sess.get("plan") or {}
check("A1 /plan writes a markdown file under the workspace",
      r.get("ok") is True and os.path.isfile(r.get("path"))
      and os.path.realpath(r["path"]).startswith(os.path.realpath(ws)), r.get("path"))
check("A2 the path is .longrun/documents/plans/<slug>-<date>.md",
      r["rel_path"].startswith(".longrun/documents/plans/")
      and r["rel_path"].endswith(".md"), r.get("rel_path"))
check("A3 the session is LOCKED and the plan is proposed",
      sess.get("plan_mode") is True and plan.get("status") == "proposed", plan.get("status"))
check("A4 the document metadata rides on the SAME plan object",
      (plan.get("doc") or {}).get("kind") == "plan"
      and (plan.get("doc") or {}).get("path") == r["path"], plan.get("doc"))
check("A5 steps come from the document, not from a second store",
      r.get("steps") == ["Add GET /health — evidence of done: curl returns 200.",
                         "Add the acceptance test — evidence of done: vNNN green."], r.get("steps"))
g = taskgraph.load(sid)
check("A6 the task graph is UNTOUCHED (plan is not the todolist)",
      not (g and g.get("nodes")), (g or {}).get("nodes"))
check("A7 the status view is the source the bar reads",
      docs.status(sid)["plan_mode"] is True
      and docs.status(sid)["active"]["status"] == "proposed"
      and docs.status(sid)["active"]["exists"] is True)

# ------------------------------------------------------------- B: approve
before = docs.status(sid)
app = docs.approve(sid)
after = stores.load_session(sid)
check("B1 approve releases the lock and keeps the document",
      app.get("plan_mode") is False and after.get("plan_mode") is False
      and (after.get("plan") or {}).get("status") == "approved"
      and os.path.isfile(before["active"]["path"]))
check("B2 the document status follows the approval",
      docs.status(sid)["active"]["status"] == "approved")
try:
    docs.approve(sid)
    check("B3 a second approve is refused (it names no proposed plan)", False, "no raise")
except ValueError as exc:
    check("B3 a second approve is refused (it names no proposed plan)", "no proposed" in str(exc), str(exc))

# --------------------------------------------------------------- C: reject
stub_plan()
docs.create_plan(sid, "reject me")
rej = docs.reject(sid)
check("C1 reject marks the document and releases the lock in THIS flow",
      docs.status(sid)["active"]["status"] == "rejected" and rej.get("plan_mode") is False,
      docs.status(sid)["active"]["status"])
stub_plan()
docs.create_plan(sid, "unlock me")
_unlock_path = docs.status(sid)["active"]["path"]
unl = docs.unlock(sid)
check("C2 unlock releases the lock AND forgets the record (bar can close)",
      unl.get("plan_mode") is False and unl.get("active") is None
      and stores.load_session(sid).get("plan") is None
      and os.path.isfile(_unlock_path), unl.get("active"))

# ---------------------------------------------------------------- D: /spec
ws2 = os.path.join(TMP, "ws-spec")
os.makedirs(ws2, exist_ok=True)
sid2 = session(ws2)
stub_spec()
sp = docs.create_spec(sid2, "add a health endpoint")
folder = sp.get("folder") or ""
names = sorted(os.path.basename(x["path"]) for x in sp.get("documents") or [])
check("D1 /spec writes exactly spec.md + tasks.md + checklist.md in ONE folder",
      names == ["checklist.md", "spec.md", "tasks.md"]
      and all(os.path.isfile(x["path"]) for x in sp["documents"]), names)
check("D2 the folder is under .longrun/documents/specs/<slug>",
      os.path.basename(folder) == "add-a-health-endpoint"
      and os.path.realpath(folder).startswith(os.path.realpath(ws2)), folder)
check("D3 the spec locks the session and records all three documents",
      stores.load_session(sid2).get("plan_mode") is True
      and (stores.load_session(sid2).get("plan") or {}).get("doc", {}).get("kind") == "spec"
      and len((stores.load_session(sid2).get("plan") or {}).get("doc", {}).get("documents") or []) == 3)
check("D4 tasks.md supplies the steps",
      sp.get("steps") == ["add the route", "verify live"], sp.get("steps"))
sp2 = docs.create_spec(sid2, "add a health endpoint")
check("D5 a second spec with the same slug gets its own folder",
      os.path.basename(sp2["folder"]).endswith("-2"), sp2["folder"])

# -------------------------------------------------------- E: no partial work
ws3 = os.path.join(TMP, "ws-fail")
os.makedirs(ws3, exist_ok=True)
sid3 = session(ws3)
docs._generate_plan_doc = lambda goal, model=None, context="": (_ for _ in ()).throw(RuntimeError("no model available for document generation"))
try:
    docs.create_plan(sid3, "boom")
    check("E1 a planner failure raises", False, "no raise")
except RuntimeError as exc:
    check("E1 a planner failure raises", "no model" in str(exc), str(exc))
check("E2 no plan file, no lock and no proposal survive a failure",
      not os.path.isdir(os.path.join(ws3, ".longrun", "documents", "plans"))
      and stores.load_session(sid3).get("plan_mode") is not True
      and not (stores.load_session(sid3).get("plan") or {}).get("doc"))

stub_spec({"spec.md": SPEC_MD, "tasks.md": "", "checklist.md": CHECK_MD})
try:
    docs.create_spec(sid3, "partial spec")
    check("E3 an incomplete spec set is refused", False, "no raise")
except ValueError as exc:
    check("E3 an incomplete spec set is refused", "tasks.md" in str(exc), str(exc))
check("E4 no spec folder is created for an incomplete set",
      not os.path.isdir(os.path.join(ws3, ".longrun", "documents", "specs")))

# ------------------------------------------------------------ F: path safety
real_cfg = docs.load_config
try:
    cfg = dict(real_cfg())
    cfg["root"] = "../outside"
    docs.load_config = lambda: dict(cfg)
    stub_plan()
    try:
        docs.create_plan(sid3, "escape")
        check("F1 a documents root outside the workspace is refused", False, "no raise")
    except ValueError as exc:
        check("F1 a documents root outside the workspace is refused", "workspace" in str(exc), str(exc))
finally:
    docs.load_config = real_cfg

tmp_cfg = os.path.join(TMP, "documents.yaml")
with open(tmp_cfg, "w", encoding="utf-8") as f:
    f.write("documents:\n  root: .longrun/documents\n  plans: ../x\n  specs: ../y\n")
orig_path = docs._config_path
try:
    docs._config_path = lambda: tmp_cfg
    bad = docs.load_config()
    check("F2 an unsafe plans/specs component falls back to the default",
          bad["plans"] == "plans" and bad["specs"] == "specs", (bad["plans"], bad["specs"]))
finally:
    docs._config_path = orig_path

# ------------------------------------- G: .longrun/documents survives adoption
ws4 = os.path.join(TMP, "ws-adopt")
os.makedirs(os.path.join(ws4, ".longrun", "documents", "plans"), exist_ok=True)
fswrite.write_text(os.path.join(ws4, ".longrun", "documents", "plans", "x.md"), "# Plan\n")
fswrite.write_text(os.path.join(ws4, ".longrun", "state.json"), "{}")
dest = paths.workspace_state_dir(ws4)
check("G1 the legacy STATE is adopted into the data home",
      os.path.isfile(os.path.join(dest, "state.json"))
      and not os.path.isfile(os.path.join(ws4, ".longrun", "state.json")), dest)
check("G2 the operator's documents STAY in the workspace",
      os.path.isfile(os.path.join(ws4, ".longrun", "documents", "plans", "x.md")))

# ---------------------------------------------------------- H: stale document
stub_plan()
docs.create_plan(sid3, "stale me")
st = docs.status(sid3)["active"]
os.remove(st["path"])
st2 = docs.status(sid3)["active"]
check("H1 a deleted document is reported stale, never hidden",
      st2["stale"] is True and st2["exists"] is False, st2.get("stale"))

# --------------------------------------------------------------- I: wiring
HTTPAPI = read("src", "longrun", "core", "api_v02.py")
check("I1 the create routes call the module, not the taskgraph",
      "_docs.create_plan" in HTTPAPI and "_docs.create_spec" in HTTPAPI
      and "generate_plan(" not in HTTPAPI.split('if path in ("/api/docs/plan"')[1].split(
          'if path in ("/api/docs/approve"')[0])
check("I2 every decision publishes its event",
      '"docs.created"' in HTTPAPI and '"docs.approved"' in HTTPAPI
      and '"docs.rejected"' in HTTPAPI and '"docs.unlocked"' in HTTPAPI)

# ------------------------------------------------ J: the live hang (2026-11-16)
# The create route published `kind=` — which `_publish(kind, **data)` already owns —
# so the handler raised TypeError AFTER the document was written and the session
# locked: no response ever reached the browser, the card spun forever and the
# operator saw "generating plan…" from the previous night.
from longrun.core import api_v02  # noqa: E402
check("J1 no publish call passes the RESERVED envelope key `kind`",
      'doc_kind=res.get("kind")' in HTTPAPI
      and " kind=res.get(" not in HTTPAPI and ", kind=res.get(" not in HTTPAPI)
_ev = api_v02._publish("docs.created", session="S-J1", doc_kind="plan",
                       path="/tmp/plan.md")
check("J2 the docs event publishes and keeps its own kind",
      isinstance(_ev, dict) and _ev.get("kind") == "docs.created"
      and _ev.get("doc_kind") == "plan", _ev)
UI1052 = read("webui", "index.html")
check("J3 a hung planner ends in an explicit, dismissible failure card",
      "_docFailCard" in UI1052 and "_docFailCard(kind," in UI1052
      and "AbortController" in UI1052 and "DOC_WAIT_MS" in UI1052
      and "dc-dismiss" in UI1052 and ".docCard.failed" in UI1052)
check("J4 the timeout says the planner may still be running (no false promise)",
      "may still be running" in UI1052)
# The lock was COSMETIC: classify() read the session out of `args`, which no
# production door fills — so a locked chat (and /api/tools/call) could still
# write. It now takes the session explicitly, and both doors pass it.
from longrun.tools import registry  # noqa: E402
_lock_sid = stores.get_or_create_session(None, title="v1052 J5")["id"]
stores.set_plan_mode(_lock_sid, True)
_d1, _r1 = registry.classify("fs.write", {"path": "/tmp/x", "content": "y"},
                             session=_lock_sid)
stores.set_plan_mode(_lock_sid, False)
_d2, _r2 = registry.classify("fs.write", {"path": "/tmp/x", "content": "y"},
                             session=_lock_sid)
check("J5 classify() takes the SESSION itself, so the lock is real",
      _d1 == "denied" and "plan mode" in _r1 and "plan mode" not in str(_r2),
      (_d1, _r1[:60], _d2))
check("J6 both production doors hand classify() the session",
      'session=(getattr(st, "session", None)' in HTTPAPI
      and "session=run_id" in HTTPAPI)

# ------------------------------------- K: one writer per session (autonomous use)
# A document write and a chat turn both save the SAME session object. With no
# operator watching, the later save silently drops the other's messages — so every
# document mutation refuses while a turn is in flight, and a second generate for
# the same session is refused instead of paying twice and overwriting the record.
_ksid = session(os.path.join(TMP, "ws-busy"))
_orig_turn = docs._turn_active
_refused = []
try:
    docs._turn_active = lambda sid: True
    for _fn, _args in ((docs.create_plan, ("x",)), (docs.create_spec, ("x",)),
                       (docs.approve, ()), (docs.reject, ()), (docs.unlock, ())):
        try:
            _fn(_ksid, *_args)
            _refused.append("")
        except ValueError as exc:
            _refused.append("chat turn" in str(exc))
finally:
    docs._turn_active = _orig_turn
check("K1 every document write refuses while a chat turn owns the session",
      all(_refused) and len(_refused) == 5, _refused)
docs._INFLIGHT.add(_ksid)
try:
    stub_plan()
    docs.create_plan(_ksid, "double")
    check("K2 a second generation for the same session is refused", False, "no raise")
except ValueError as exc:
    check("K2 a second generation for the same session is refused",
          "already being generated" in str(exc), str(exc))
finally:
    docs._INFLIGHT.discard(_ksid)
stub_plan()
_kr = docs.create_plan(_ksid, "after the double")
check("K3 the in-flight slot is released, so the next attempt works",
      _kr.get("ok") is True and _ksid not in docs._INFLIGHT)
check("K4 the busy probe is the events module's own predicate (no second truth)",
      "events.turn_active" in read("src", "longrun", "plan", "docs.py"))

# ------------------------- L: a hard kill leaves no half-spec (v1051c)
# The three files are written into `.tmp-<uuid>` and renamed only when all exist,
# so a killed writer (service restart) never publishes a partial spec — but it can
# leave the temp folder. The next create removes it under the same `_LOCK`.
_ws_l = os.path.join(TMP, "ws-sweep")
os.makedirs(_ws_l, exist_ok=True)
_sid_l = session(_ws_l)
stub_spec()
_l_folder = docs.spec_dir(_sid_l)
os.makedirs(os.path.join(_l_folder, ".tmp-deadbeef"), exist_ok=True)
fswrite.write_text(os.path.join(_l_folder, ".tmp-deadbeef", "spec.md"), "# half\n")
docs.create_spec(_sid_l, "add a health endpoint")
_left = sorted(os.listdir(_l_folder))
check("L1 the next spec sweeps a temp set left by a killed writer",
      ".tmp-deadbeef" not in _left and _left == ["add-a-health-endpoint"], _left)

# ------------------------------- M: the CLI twin (v1051c, operator request)
# "usa la CLI per fare sessioni vere": the same document commands must exist on
# the terminal client, pointing at the SAME endpoints as the WebUI — a CLI route
# that only looks similar is a second truth.
FORGE_SRC = read("src", "longrun", "core", "forge.py")
CLI_MD = read("docs", "CLI.md")
_docs_parser = FORGE_SRC.split('add_parser("docs")')[1][:400] if 'add_parser("docs")' in FORGE_SRC else ""
check("M1 the CLI has a docs group with the six document actions",
      "def cmd_docs(args):" in FORGE_SRC
      and all('"%s"' % a in _docs_parser
              for a in ("status", "plan", "spec", "approve", "reject", "unlock")),
      _docs_parser[:200])
check("M2 docs uses the WebUI's own endpoints (no parallel route)",
      '"/api/docs?session="' in FORGE_SRC
      and all('"/api/docs/%s"' % a in FORGE_SRC
              for a in ("plan", "spec", "approve", "reject", "unlock")))
check("M3 sessions new can name a workspace through the WebUI's route",
      'add_argument("--workspace")' in FORGE_SRC
      and '"/api/sessions/new?title="' in FORGE_SRC)
check("M4 docs/CLI.md documents the group and its endpoints",
      "### Documents (`/plan` and `/spec`)" in CLI_MD
      # `--session` became optional with the CLI current-session pointer (2026-11-16).
      and "| `docs unlock [--session ID]` |" in CLI_MD
      and "| POST | `/api/docs/plan` | `docs plan` |" in CLI_MD
      and "`sessions new \"title\" [--workspace DIR]`" in CLI_MD)

# ------------------- N: the AGENT path — `docs` tool + live document fields ----
# Operator: "gli agenti hanno i tool per entrare da soli in spec/plan e comandare
# i team member che riportano a lui?". The tool exists now; these pins hold the two
# things that make it safe: the owner path, and a turn's stale save not dropping
# (or resurrecting) the document record.
from longrun.tools import registry as _reg  # noqa: E402
from longrun.tools import tools as _toolmod  # noqa: E402

TOOLS_SRC = read("src", "longrun", "tools", "tools.py")
REG_SRC = read("src", "longrun", "tools", "registry.py")
TOOLS_YAML = read("config", "tools.yaml")

_ws_n = os.path.join(TMP, "ws-agent-docs")
os.makedirs(_ws_n, exist_ok=True)
_sid_n = session(_ws_n)
_orig_turn_n = docs._turn_active
try:
    docs._turn_active = lambda sid: True
    stub_plan()
    r_owner = docs.create_plan(_sid_n, "owner path", owner=True)
    try:
        docs.create_plan(_sid_n, "http path", owner=False)
        _http_refused = False
    except ValueError as exc:
        _http_refused = "chat turn" in str(exc)
finally:
    docs._turn_active = _orig_turn_n
check("N1 the owner path writes inside a turn; the HTTP path still refuses",
      r_owner.get("ok") is True and _http_refused)

# A turn loads the session at its start and saves the WHOLE dict at its end. The
# live doc fields are what stop that stale copy from dropping the new record.
_sid_live = session(_ws_n)
_stale = stores.load_session(_sid_live)          # an OLD turn's snapshot: no plan
docs._turn_active = lambda sid: True
try:
    stub_plan()
    docs.create_plan(_sid_live, "live plan", owner=True)
finally:
    docs._turn_active = _orig_turn_n
stores.save_session(_stale)          # the "running turn" writes its old snapshot
_now = stores.load_session(_sid_live)
check("N2 a stale turn save cannot drop the new document",
      bool(_now.get("plan_mode")) and ((_now.get("plan") or {}).get("doc") or {}).get("kind") == "plan")
docs.unlock(_sid_live)
stores.save_session(_stale)          # the same old snapshot lands again, after unlock
_now2 = stores.load_session(_sid_live)
check("N3 the same stale save cannot resurrect an unlocked document",
      _now2.get("plan") is None and _now2.get("plan_mode") is False)

# Permission: another session only when it is a DIRECT report (the dispatch rule).
from longrun.agent import agents as _agents  # noqa: E402
_orig_reg = (_agents.REGISTRY.get, _agents.REGISTRY.resolve, _agents.REGISTRY.team_of)
_caller = "session-of-the-head"
_target_sid = "session-of-the-report"
stores.get_or_create_session(_target_sid, title="report", workspace=_ws_n)
try:
    _agents.REGISTRY.get = lambda sid: ({"id": "A54"} if sid == _caller else None)
    _agents.REGISTRY.team_of = lambda ref, depth=1: ["A54", "A48"]
    _agents.REGISTRY.resolve = lambda ref: (
        {"id": "A48", "session": _target_sid} if ref in ("A48", _target_sid) else None)
    _ok = _toolmod._docs_tool({"action": "status", "session": _target_sid}, _caller)
    _agents.REGISTRY.resolve = lambda ref: ({"id": "A49", "session": "x"} if ref == "A49" else None)
    _no = _toolmod._docs_tool({"action": "status", "session": "A49"}, _caller)
finally:
    (_agents.REGISTRY.get, _agents.REGISTRY.resolve, _agents.REGISTRY.team_of) = _orig_reg
check("N4 a direct report is a legal target; a stranger is refused",
      _ok.get("ok") is True and _ok.get("session") == _target_sid
      and _no.get("ok") is False and "direct reports" in str(_no.get("error")), (_ok, _no))

_enum = _reg._LEGACY_SCHEMAS["docs"]["properties"]["action"]["enum"]
_handler_src = TOOLS_SRC.split("def _docs_tool")[1].split("_DISPATCH = {")[0]
check("N5 approval/rejection/unlock stay with the OPERATOR (not in the tool)",
      _enum == ["plan", "spec", "status"]
      and '"approve"' not in _handler_src and '"unlock"' not in _handler_src)
check("N6 the tool is registered and reusable from the registry",
      _reg._SUBTOOL_FIELDS["docs"] == {"plan": ["prompt", "session", "context"],
                                       "spec": ["prompt", "session", "context"],
                                       "status": ["session"]}
      and all(k in _reg._SUBTOOL_GUIDANCE for k in ("docs.plan", "docs.spec", "docs.status"))
      and _reg._SUBTOOL_REQUIRED["docs.plan"] == ["prompt"]
      and _toolmod._DISPATCH.get("docs") is _toolmod._docs_tool
      and "docs" not in _reg.PLAN_GATED_TOOLS
      and "  docs:\n    enabled: true\n    approval: auto" in TOOLS_YAML)
_seen = {}
_orig_gen_n = docs._generate_plan_doc
try:
    docs._generate_plan_doc = lambda goal, model=None, context="": (
        _seen.update(ctx=context) or (PLAN_MD, "fake-model"))
    docs.create_plan(_sid_n, "with notes", extra_context="THE AGENT READ main.py:1-40", owner=True)
finally:
    docs._generate_plan_doc = _orig_gen_n
check("N7 the caller's own notes reach the planner, bounded and labelled",
      "AGENT NOTES" in _seen.get("ctx", "") and "main.py:1-40" in _seen.get("ctx", "")
      and len(_seen.get("ctx", "")) < 4096 + 8192 + 200, len(_seen.get("ctx", "")))

docs._generate_plan_doc = _orig_plan
docs._generate_spec_docs = _orig_spec

print("\n---\nv1052: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
